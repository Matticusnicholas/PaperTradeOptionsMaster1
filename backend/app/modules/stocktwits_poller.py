"""StockTwits poller – fetch public sentiment stream per ticker (free, no auth)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from app.config import STOCKTWITS_POLL_SECONDS, WATCHLIST
from app.database import SessionLocal
from app.models.tables import NewsItem
from app.modules.event_bus import event_bus

logger = logging.getLogger("stocktwits_poller")

API_BASE = "https://api.stocktwits.com/api/2/streams/symbol"
SOURCE_TIER = 2  # Fast/social tier
SOURCE_TYPE = "stocktwits"

# Rate limiting: StockTwits allows ~200 req/hour
_last_request = 0.0
_MIN_INTERVAL = 3.0


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]


class StockTwitsPoller:
    """Poll StockTwits public API for per-ticker sentiment messages."""

    def __init__(self) -> None:
        self.tickers = list(WATCHLIST.keys())
        self.poll_interval = STOCKTWITS_POLL_SECONDS
        self._seen_ids: set = set()
        self._last_message_id: Dict[str, int] = {}  # ticker -> last seen msg id

    async def poll_once(self) -> List[NewsItem]:
        """Poll StockTwits for all watchlist tickers."""
        all_items: List[NewsItem] = []
        for ticker in self.tickers:
            try:
                items = await self._fetch_ticker(ticker)
                all_items.extend(items)
            except Exception as exc:
                logger.debug("StockTwits error for %s: %s", ticker, exc)
                # Don't spam events for expected rate limits
                if "429" in str(exc) or "rate" in str(exc).lower():
                    await asyncio.sleep(30)
                    break

        if all_items:
            await event_bus.emit(
                "NEWS_FETCHED", "stocktwits_poller",
                payload={
                    "source": "stocktwits",
                    "count": len(all_items),
                    "tickers_polled": len(self.tickers),
                },
            )
        return all_items

    async def _fetch_ticker(self, ticker: str) -> List[NewsItem]:
        """Fetch recent messages for a single ticker."""
        global _last_request

        elapsed = time.time() - _last_request
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)

        url = f"{API_BASE}/{ticker}.json"
        params = {}
        last_id = self._last_message_id.get(ticker)
        if last_id:
            params["since"] = last_id

        _last_request = time.time()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, params=params,
                timeout=15,
                follow_redirects=True,
            )
            if resp.status_code == 429:
                logger.warning("StockTwits rate limited")
                return []
            resp.raise_for_status()
            data = resp.json()

        messages = data.get("messages", [])
        if not messages:
            return []

        # Track highest message id for next poll
        max_id = max(m.get("id", 0) for m in messages)
        if max_id:
            self._last_message_id[ticker] = max_id

        items: List[NewsItem] = []
        db = SessionLocal()

        try:
            for msg in messages:
                msg_id = msg.get("id", 0)
                if msg_id in self._seen_ids:
                    continue

                body = msg.get("body", "").strip()
                if not body or len(body) < 10:
                    continue

                # StockTwits provides sentiment if user tagged it
                st_sentiment = msg.get("entities", {}).get("sentiment", {})
                sentiment_tag = st_sentiment.get("basic") if st_sentiment else None
                # "Bullish" or "Bearish" from StockTwits users

                created_str = msg.get("created_at", "")
                try:
                    ts = datetime.strptime(
                        created_str, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    ts = datetime.now(timezone.utc)

                guid = _hash(f"stocktwits:{msg_id}")

                exists = db.query(NewsItem).filter_by(guid=guid).first()
                if exists:
                    self._seen_ids.add(msg_id)
                    continue

                # Add StockTwits user sentiment to the text for our engine to parse
                enriched_body = body
                if sentiment_tag:
                    enriched_body = f"[{sentiment_tag}] {body}"

                user = msg.get("user", {})
                username = user.get("username", "unknown")

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
