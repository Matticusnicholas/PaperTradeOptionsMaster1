"""Reddit poller – scrapes subreddits for finance posts using public JSON API."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from app.config import REDDIT_POLL_SECONDS, REDDIT_SUBREDDITS, WATCHLIST
from app.database import SessionLocal
from app.models.tables import NewsItem
from app.modules.event_bus import event_bus

logger = logging.getLogger("reddit_poller")

USER_AGENT = "SentimentOptionsLab/1.0 (research bot)"

# Tier 2 source (fast/social, needs cross-confirmation)
SOURCE_TIER = 2

# Rate limiting
_last_request = 0.0
_MIN_INTERVAL = 2.0  # seconds between Reddit requests


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]


class RedditPoller:
    """Poll Reddit subreddits for finance-relevant posts."""

    def __init__(self) -> None:
        self.subreddits = REDDIT_SUBREDDITS
        self.poll_interval = REDDIT_POLL_SECONDS
        self._seen_ids: set = set()
        # Build quick ticker mention checker from watchlist
        self._ticker_patterns: Dict[str, re.Pattern] = {}
        for ticker, aliases in WATCHLIST.items():
            parts = [re.escape(a) for a in aliases] + [
                r"\$" + re.escape(ticker),
                r"\b" + re.escape(ticker) + r"\b",
            ]
            self._ticker_patterns[ticker] = re.compile(
                "|".join(parts), re.IGNORECASE
            )

    async def poll_once(self) -> List[NewsItem]:
        """Single poll cycle across all subreddits."""
        all_items: List[NewsItem] = []
        for sub in self.subreddits:
            try:
                items = await self._fetch_subreddit(sub)
                all_items.extend(items)
            except Exception as exc:
                logger.error("Reddit poll error r/%s: %s", sub, exc)
                await event_bus.emit(
                    "ERROR", "reddit_poller",
                    severity="warning",
                    payload={"subreddit": sub, "error": str(exc)},
                )

        if all_items:
            await event_bus.emit(
                "NEWS_FETCHED", "reddit_poller",
                payload={
                    "source": "reddit",
                    "count": len(all_items),
                    "subreddits_polled": len(self.subreddits),
                },
            )
        return all_items

    async def _fetch_subreddit(self, subreddit: str) -> List[NewsItem]:
        """Fetch new posts from a subreddit's JSON endpoint."""
        global _last_request

        # Rate limit
        elapsed = time.time() - _last_request
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)

        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
        _last_request = time.time()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=15,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()

        posts = data.get("data", {}).get("children", [])
        items: List[NewsItem] = []
        db = SessionLocal()

        try:
            for post in posts:
                pd = post.get("data", {})
                post_id = pd.get("id", "")

                # Skip already seen
                if post_id in self._seen_ids:
                    continue

                title = pd.get("title", "").strip()
                if not title:
                    continue

                selftext = pd.get("selftext", "")[:1000]
                combined = f"{title} {selftext}"

                # Quick relevance check: does it mention any watchlist ticker?
                if not self._is_relevant(combined):
                    continue

                permalink = pd.get("permalink", "")
                link_url = f"https://reddit.com{permalink}" if permalink else ""
                created_utc = pd.get("created_utc", 0)
                ts = datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else datetime.now(timezone.utc)
                guid = _hash(f"reddit:{post_id}")

                # DB dedup
                exists = db.query(NewsItem).filter_by(guid=guid).first()
                if exists:
                    self._seen_ids.add(post_id)
                    continue

                # Determine source tier — Reddit is tier 2 by default,
                # but posts linking to tier 1 sources get tier 1
                link_domain = pd.get("domain", "")
                tier = self._classify_link_tier(link_domain)

                item = NewsItem(
                    guid=guid,
                    ts=ts,
                    source=f"r/{subreddit}",
                    source_type="reddit",
                    source_tier=tier,
                    url=link_url,
                    title=title,
                    summary=selftext[:500] if selftext else title,
                    text=selftext,
                    raw_hash=_hash(title),
                )
                db.add(item)
                db.commit()
                db.refresh(item)

                self._seen_ids.add(post_id)
                items.append(item)

                await event_bus.emit(
                    "NEWS_PARSED", "reddit_poller",
                    payload={
                        "news_id": item.id,
                        "title": title[:200],
                        "source": f"r/{subreddit}",
                        "source_type": "reddit",
                        "source_tier": tier,
                    },
                )
        finally:
            db.close()

        # Cap seen IDs to avoid memory leak
        if len(self._seen_ids) > 5000:
            self._seen_ids = set(list(self._seen_ids)[-2500:])

        return items

    def _is_relevant(self, text: str) -> bool:
        """Check if text mentions any watchlist ticker."""
        for ticker, pat in self._ticker_patterns.items():
            if pat.search(text):
                return True
        return False

    def _classify_link_tier(self, domain: str) -> int:
        """If a Reddit post links to an authoritative source, promote its tier."""
        from app.config import TIER_1_KEYWORDS
        domain_lower = domain.lower()
        for kw in TIER_1_KEYWORDS:
            if kw in domain_lower:
                return 1  # Tier 1: it's linking to Reuters/Bloomberg/etc.
        return SOURCE_TIER  # Default tier 2

    async def run_loop(self) -> None:
        """Run forever polling on interval."""
        logger.info("Reddit poller started (interval=%ds, subs=%s)",
                    self.poll_interval, self.subreddits)
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                logger.error("Reddit loop error: %s", exc)
            await asyncio.sleep(self.poll_interval)
