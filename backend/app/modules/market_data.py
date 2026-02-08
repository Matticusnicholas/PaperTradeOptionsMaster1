"""MarketDataProvider – pull underlying prices via yfinance with caching."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

import yfinance as yf

from app.modules.event_bus import event_bus

logger = logging.getLogger("market_data")

# Simple in-memory cache: ticker -> (price, timestamp)
_price_cache: Dict[str, tuple] = {}
CACHE_TTL = 60  # seconds


class MarketDataProvider:
    """Fetch underlying stock prices via yfinance, with throttling + caching."""

    def __init__(self) -> None:
        self._call_count = 0
        self._last_call = 0.0
        self._min_interval = 1.0  # seconds between calls

    @property
    def call_count(self) -> int:
        return self._call_count

    async def get_price(self, ticker: str) -> Optional[float]:
        """Get the latest price for a ticker, using cache if fresh."""
        cached = _price_cache.get(ticker)
        if cached and (time.time() - cached[1]) < CACHE_TTL:
            return cached[0]

        # Throttle
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

        try:
            loop = asyncio.get_event_loop()
            price = await loop.run_in_executor(None, self._fetch_price, ticker)
            if price is not None:
                _price_cache[ticker] = (price, time.time())
                self._call_count += 1
            return price
        except Exception as exc:
            logger.error("Failed to get price for %s: %s", ticker, exc)
            await event_bus.emit(
                "ERROR", "market_data",
                ticker=ticker,
                severity="warning",
                payload={"error": str(exc), "ticker": ticker},
            )
            # Return cached even if stale
            if cached:
                return cached[0]
            return None

    def _fetch_price(self, ticker: str) -> Optional[float]:
        self._last_call = time.time()
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            # Fallback: try history
            hist = t.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return float(price) if price else None

    async def get_prices_batch(self, tickers: list) -> Dict[str, Optional[float]]:
        """Get prices for multiple tickers."""
        results = {}
        for ticker in tickers:
            results[ticker] = await self.get_price(ticker)
        return results
