"""StockTwits poller – scrapes public StockTwits pages for sentiment data.

The official StockTwits API has been suspended for new registrations and
returns 403 for unauthenticated requests. This module scrapes the public
web pages instead, extracting message data from the embedded JSON.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from app.config import STOCKTWITS_POLL_SECONDS, WATCHLIST
from app.database import SessionLocal
from app.models.tables import NewsItem
from app.modules.event_bus import event_bus

logger = logging.getLogger("stocktwits_poller")

SOURCE_TIER = 2  # Fast/social tier
SOURCE_TYPE = "stocktwits"

# Rate limiting
_last_request = 0.0
_MIN_INTERVAL = 5.0  # Be polite — 5s between requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]


class StockTwitsPoller:
    """Poll StockTwits by scraping public ticker pages."""

    def __init__(self) -> None:
        self.tickers = list(WATCHLIST.keys())
        self.poll_interval = STOCKTWITS_POLL_SECONDS
        self._seen_ids: set = set()
        self._ticker_index = 0  # Rotate through tickers to spread load

    async def poll_once(self) -> List[NewsItem]:
        """Poll StockTwits for a batch of watchlist tickers (rotating)."""
        all_items: List[NewsItem] = []

        # Poll 3 tickers per cycle to stay under rate limits
        batch_size = min(3, len(self.tickers))
        for _ in range(batch_size):
            ticker = self.tickers[self._ticker_index % len(self.tickers)]
            self._ticker_index += 1
            try:
                items = await self._fetch_ticker(ticker)
                all_items.extend(items)
            except Exception as exc:
                logger.debug("StockTwits error for %s: %s", ticker, exc)
                if "429" in str(exc) or "403" in str(exc):
                    logger.warning("StockTwits blocked/rate-limited, backing off")
                    await asyncio.sleep(60)
                    break

        if all_items:
            await event_bus.emit(
                "NEWS_FETCHED", "stocktwits_poller",
                payload={
                    "source": "stocktwits",
                    "count": len(all_items),
                    "tickers_polled": batch_size,
                },
            )
        return all_items

    async def _fetch_ticker(self, ticker: str) -> List[NewsItem]:
        """Fetch recent messages for a single ticker by scraping the web page."""
        global _last_request

        elapsed = time.time() - _last_request
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)

        # Scrape the public symbol page
        url = f"https://stocktwits.com/symbol/{ticker}"
        _last_request = time.time()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=HEADERS,
                timeout=20,
                follow_redirects=True,
            )
            if resp.status_code in (403, 429):
                logger.warning("StockTwits %d for %s", resp.status_code, ticker)
                return []
            resp.raise_for_status()
            html = resp.text

        # Extract messages from Next.js/React embedded JSON
        messages = self._extract_messages(html, ticker)
        if not messages:
            return []

        items: List[NewsItem] = []
        db = SessionLocal()

        try:
            for msg in messages:
                msg_id = msg.get("id", "")
                if not msg_id or msg_id in self._seen_ids:
                    continue

                body = msg.get("body", "").strip()
                if not body or len(body) < 10:
                    continue

                sentiment_tag = msg.get("sentiment")
                username = msg.get("username", "unknown")
                ts_str = msg.get("created_at", "")

                try:
                    ts = datetime.strptime(
                        ts_str, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    ts = datetime.now(timezone.utc)

                guid = _hash(f"stocktwits:{msg_id}")

                exists = db.query(NewsItem).filter_by(guid=guid).first()
                if exists:
                    self._seen_ids.add(msg_id)
                    continue

                enriched_body = body
                if sentiment_tag:
                    enriched_body = f"[{sentiment_tag}] {body}"

                item = NewsItem(
                    guid=guid,
                    ts=ts,
                    source=f"stocktwits/@{username}",
                    source_type=SOURCE_TYPE,
                    source_tier=SOURCE_TIER,
                    url=f"https://stocktwits.com/message/{msg_id}",
                    title=body[:200],
                    summary=enriched_body[:500],
                    text=enriched_body,
                    raw_hash=_hash(body),
                )
                db.add(item)
                db.commit()
                db.refresh(item)

                self._seen_ids.add(msg_id)
                items.append(item)

                await event_bus.emit(
                    "NEWS_PARSED", "stocktwits_poller",
                    ticker=ticker,
                    payload={
                        "news_id": item.id,
                        "title": body[:150],
                        "source": f"stocktwits/@{username}",
                        "source_type": SOURCE_TYPE,
                        "source_tier": SOURCE_TIER,
                        "st_sentiment": sentiment_tag,
                        "ticker": ticker,
                    },
                )
        finally:
            db.close()

        if len(self._seen_ids) > 10000:
            self._seen_ids = set(list(self._seen_ids)[-5000:])

        return items

    def _extract_messages(self, html: str, ticker: str) -> List[dict]:
        """Extract message data from the StockTwits page HTML.

        StockTwits embeds data in __NEXT_DATA__ or similar JSON blobs.
        We try multiple extraction strategies.
        """
        messages = []

        # Strategy 1: __NEXT_DATA__ JSON
        next_data_match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                messages = self._walk_next_data(data)
                if messages:
                    return messages
            except (json.JSONDecodeError, KeyError):
                pass

        # Strategy 2: Look for JSON arrays of message objects
        msg_pattern = re.findall(
            r'"id"\s*:\s*(\d+)\s*,.*?"body"\s*:\s*"((?:[^"\\]|\\.){10,})".*?"username"\s*:\s*"([^"]+)"',
            html
        )
        for msg_id, body, username in msg_pattern:
            body_decoded = body.encode().decode("unicode_escape", errors="replace")
            messages.append({
                "id": msg_id,
                "body": body_decoded,
                "username": username,
                "sentiment": None,
                "created_at": "",
            })

        # Strategy 3: Simple text extraction from data attributes
        if not messages:
            msg_blocks = re.findall(
                r'data-message-id="(\d+)".*?class="[^"]*message-body[^"]*"[^>]*>(.*?)</(?:div|p|span)',
                html, re.DOTALL
            )
            for msg_id, body_html in msg_blocks:
                body = re.sub(r'<[^>]+>', '', body_html).strip()
                if body and len(body) >= 10:
                    messages.append({
                        "id": msg_id,
                        "body": body,
                        "username": "unknown",
                        "sentiment": None,
                        "created_at": "",
                    })

        return messages[:25]  # Cap at 25

    def _walk_next_data(self, data: dict) -> List[dict]:
        """Recursively walk __NEXT_DATA__ to find message arrays."""
        results = []

        def _walk(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                # Look for message-like objects
                if "body" in obj and "id" in obj:
                    user = obj.get("user", {})
                    sentiment = obj.get("entities", {}).get("sentiment", {})
                    results.append({
                        "id": str(obj["id"]),
                        "body": obj.get("body", ""),
                        "username": user.get("username", "unknown") if isinstance(user, dict) else "unknown",
                        "sentiment": sentiment.get("basic") if isinstance(sentiment, dict) else None,
                        "created_at": obj.get("created_at", ""),
                    })
                for v in obj.values():
                    _walk(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, depth + 1)

        _walk(data)
        return results

    async def run_loop(self) -> None:
        """Run forever polling on interval."""
        logger.info("StockTwits poller started (interval=%ds, tickers=%d)",
                    self.poll_interval, len(self.tickers))
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                logger.error("StockTwits loop error: %s", exc)
            await asyncio.sleep(self.poll_interval)
