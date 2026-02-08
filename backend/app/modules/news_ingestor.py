"""Stage 1 – RSS news polling, normalization, deduplication."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from difflib import SequenceMatcher

import feedparser
from sqlalchemy.orm import Session

from app.config import RSS_FEEDS, NEWS_POLL_SECONDS
from app.database import SessionLocal
from app.models.tables import NewsItem
from app.modules.event_bus import event_bus

logger = logging.getLogger("news_ingestor")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_html(raw: str) -> str:
    """Strip HTML tags."""
    return re.sub(r"<[^>]+>", "", raw or "").strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]


def _similar(a: str, b: str, threshold: float = 0.80) -> bool:
    """Quick similarity check for dedup."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


# ---------------------------------------------------------------------------
# NewsIngestor
# ---------------------------------------------------------------------------

class NewsIngestor:
    """Polls RSS feeds, normalises items, deduplicates, stores in DB."""

    def __init__(self) -> None:
        self.feeds = RSS_FEEDS
        self.poll_interval = NEWS_POLL_SECONDS
        self._recent_hashes: List[str] = []  # in-memory dedup window

    async def poll_once(self) -> List[NewsItem]:
        """Single poll cycle across all configured feeds."""
        new_items: List[NewsItem] = []
        for feed_url in self.feeds:
            try:
                items = await self._fetch_feed(feed_url)
                new_items.extend(items)
            except Exception as exc:
                logger.error("Feed error %s: %s", feed_url, exc)
                await event_bus.emit(
                    "ERROR", "news_ingestor",
                    severity="error",
                    payload={"feed": feed_url, "error": str(exc)},
                )
        if new_items:
            await event_bus.emit(
                "NEWS_FETCHED", "news_ingestor",
                payload={"count": len(new_items), "feeds_polled": len(self.feeds)},
            )
        return new_items

    async def _fetch_feed(self, url: str) -> List[NewsItem]:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, url)
        source_name = feed.feed.get("title", url)[:200]
        items: List[NewsItem] = []
        db: Session = SessionLocal()
        try:
            for entry in feed.entries:
                item = self._normalize(entry, source_name, url)
                if item is None:
                    continue
                # DB dedup by guid
                exists = db.query(NewsItem).filter_by(guid=item.guid).first()
                if exists:
                    continue
                # Similarity dedup against recent
                if self._is_duplicate(item.title):
                    continue
                db.add(item)
                db.commit()
                db.refresh(item)
                self._recent_hashes.append(item.raw_hash)
                items.append(item)

                await event_bus.emit(
                    "NEWS_PARSED", "news_ingestor",
                    payload={
                        "news_id": item.id,
                        "title": item.title[:200],
                        "source": item.source,
                    },
                )
        finally:
            db.close()

        # Trim in-memory dedup cache
        if len(self._recent_hashes) > 2000:
            self._recent_hashes = self._recent_hashes[-1000:]

        return items

    def _normalize(self, entry, source: str, feed_url: str) -> Optional[NewsItem]:
        title = _clean_html(entry.get("title", ""))
        if not title:
            return None
        summary = _clean_html(entry.get("summary", ""))
        link = entry.get("link", "")
        guid_raw = entry.get("id", "") or link or title
        guid = _hash_text(guid_raw + source)

        pub = entry.get("published_parsed") or entry.get("updated_parsed")
        ts = datetime(*pub[:6], tzinfo=timezone.utc) if pub else datetime.now(timezone.utc)

        return NewsItem(
            guid=guid,
            ts=ts,
            source=source,
            url=link,
            title=title,
            summary=summary,
            text=summary,  # RSS usually only gives summary
            raw_hash=_hash_text(title),
        )

    def _is_duplicate(self, title: str) -> bool:
        h = _hash_text(title)
        if h in self._recent_hashes:
            return True
        # Check similarity against last 50 items
        db: Session = SessionLocal()
        try:
            recent = (
                db.query(NewsItem.title)
                .order_by(NewsItem.id.desc())
                .limit(50)
                .all()
            )
            for (recent_title,) in recent:
                if _similar(title, recent_title):
                    return True
        finally:
            db.close()
        return False

    async def run_loop(self) -> None:
        """Run forever polling on interval."""
        logger.info("NewsIngestor loop started (interval=%ds)", self.poll_interval)
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                logger.error("NewsIngestor loop error: %s", exc)
            await asyncio.sleep(self.poll_interval)
