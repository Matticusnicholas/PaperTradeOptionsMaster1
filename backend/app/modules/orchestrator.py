"""Orchestrator – coordinates all pipeline stages with two operating modes.

Modes:
  - "trade" (default): Full pipeline with paper trading
  - "signal": Alert-only mode — no trades, just signals + push notifications

Enhanced with:
  - Reddit + StockTwits social polling
  - Source tier classification
  - Trigger-based immediate options fetch on confirmed candidates
  - Flow detection (unusual options activity)
  - Off-hours news scanning with alert generation
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from app.config import (
    DECISION_TICK_MINUTES,
    MAX_NEW_TRADES_PER_TICK,
    NEWS_POLL_SECONDS,
    REDDIT_POLL_SECONDS,
    SOCIAL_ENABLED,
    STOCKTWITS_POLL_SECONDS,
    TIER_1_KEYWORDS,
)
from app.database import SessionLocal
from app.models.tables import Candidate, NewsItem
from app.modules.candidate_funnel import CandidateFunnel
from app.modules.coverage_tracker import CoverageIntensityTracker
from app.modules.event_bus import event_bus
from app.modules.flow_detector import FlowDetector
from app.modules.greeks import GreeksCalculator
from app.modules.market_clock import MarketClock
from app.modules.market_data import MarketDataProvider
from app.modules.news_ingestor import NewsIngestor
from app.modules.options_chain import OptionsChainProvider
from app.modules.options_engine import OptionsEngine
from app.modules.reddit_poller import RedditPoller
from app.modules.risk_engine import RiskEngine
from app.modules.sentiment_engine import AnalystStyleSentimentEngine
from app.modules.sim_broker import SimBroker
from app.modules.stocktwits_poller import StockTwitsPoller
from app.modules.ticker_resolver import TickerResolver

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """Coordinates all pipeline stages in async background loops."""

    def __init__(self, mode: str = "signal") -> None:
        """
        Args:
            mode: "trade" for paper trading, "signal" for alert-only dashboard.
        """
        self.mode = mode

        # Stage 1: News + Social
        self.news_ingestor = NewsIngestor()
        self.reddit_poller = RedditPoller()
        self.stocktwits_poller = StockTwitsPoller()
        self.ticker_resolver = TickerResolver()
        self.sentiment_engine = AnalystStyleSentimentEngine()
        self.coverage_tracker = CoverageIntensityTracker()
        self.candidate_funnel = CandidateFunnel()

        # Stage 2: Options + Trading
        self.market_data = MarketDataProvider()
        self.options_chain = OptionsChainProvider()
        self.greeks_calc = GreeksCalculator()
        self.options_engine = OptionsEngine()
        self.risk_engine = RiskEngine()
        self.flow_detector = FlowDetector()

        # Only init broker in trade mode
        self.sim_broker: Optional[SimBroker] = None
        if mode == "trade":
            self.sim_broker = SimBroker(self.market_data)

        self.market_clock = MarketClock()
        self._running = False
        self._trigger_queue: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        """Start all background loops."""
        self._running = True
        logger.info("Orchestrator starting in %s mode...", self.mode.upper())

        await event_bus.emit(
            "MARKET_CLOCK_STATUS", "orchestrator",
            payload={
                "message": f"Orchestrator starting ({self.mode} mode)",
                "mode": self.mode,
            },
        )

        loops = [
            self._news_loop(),
            self._trigger_loop(),
            self._clock_loop(),
        ]

        if SOCIAL_ENABLED:
            loops.append(self._reddit_loop())
            loops.append(self._stocktwits_loop())
            logger.info("Social pollers enabled (Reddit + StockTwits)")

        if self.mode == "trade":
            loops.append(self._decision_loop())
            loops.append(self._monitor_loop())
        else:
            # Signal mode: scan during AND off market hours
            loops.append(self._signal_scan_loop())

        await asyncio.gather(*loops, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False

    # ── Shared: process news items through Stage 1 pipeline ──

    async def _process_news_items(self, items: List[NewsItem]) -> None:
        """Run Stage 1: resolve tickers → score sentiment → update coverage → funnel."""
        affected_tickers = set()

        for item in items:
            # Classify source tier for RSS items
            if item.source_type == "rss" and (item.source_tier is None or item.source_tier == 2):
                item.source_tier = self._classify_source_tier(item.source or "")

            mentions = await self.ticker_resolver.resolve(item)
            for mention in mentions:
                await self.sentiment_engine.analyze_news(item, mention.ticker)
                affected_tickers.add(mention.ticker)

        for ticker in affected_tickers:
            await self.coverage_tracker.update(ticker)

        if affected_tickers:
            candidates = await self.candidate_funnel.evaluate()

            # Queue trigger-fetch for high-confidence candidates
            for c in candidates:
                if c.cross_tier_confirmed or c.urgency >= 60:
                    await self._trigger_queue.put(c)
                    logger.info(
                        "TRIGGER queued: %s (urgency=%.1f, cross_tier=%s)",
                        c.ticker, c.urgency, c.cross_tier_confirmed,
                    )

    def _classify_source_tier(self, source_name: str) -> int:
        source_lower = source_name.lower()
        for kw in TIER_1_KEYWORDS:
            if kw in source_lower:
                return 1
        return 2

    # ── Stage 1 Loops ──

    async def _news_loop(self) -> None:
        """RSS news polling loop."""
        logger.info("RSS loop started (interval=%ds)", NEWS_POLL_SECONDS)
        while self._running:
            try:
                items = await self.news_ingestor.poll_once()
                if items:
                    await self._process_news_items(items)
            except Exception as exc:
                logger.error("News loop error: %s", exc, exc_info=True)
                await event_bus.emit("ERROR", "orchestrator", severity="error",
                                     payload={"loop": "news", "error": str(exc)})
            await asyncio.sleep(NEWS_POLL_SECONDS)

    async def _reddit_loop(self) -> None:
        """Reddit polling loop (faster than RSS)."""
        logger.info("Reddit loop started (interval=%ds)", REDDIT_POLL_SECONDS)
        while self._running:
            try:
                items = await self.reddit_poller.poll_once()
                if items:
                    await self._process_news_items(items)
            except Exception as exc:
                logger.error("Reddit loop error: %s", exc, exc_info=True)
            await asyncio.sleep(REDDIT_POLL_SECONDS)

    async def _stocktwits_loop(self) -> None:
        """StockTwits polling loop."""
        logger.info("StockTwits loop started (interval=%ds)", STOCKTWITS_POLL_SECONDS)
        while self._running:
            try:
                items = await self.stocktwits_poller.poll_once()
                if items:
                    await self._process_news_items(items)
            except Exception as exc:
                logger.error("StockTwits loop error: %s", exc, exc_info=True)
            await asyncio.sleep(STOCKTWITS_POLL_SECONDS)

    # ── Trigger-based immediate options fetch + alert ──

    async def _trigger_loop(self) -> None:
        """Immediately fetch options + detect flow when a candidate is confirmed."""
        logger.info("Trigger loop started (immediate fetch on confirmed signals)")
        while self._running:
            try:
                candidate = await asyncio.wait_for(self._trigger_queue.get(), timeout=30)
            except asyncio.TimeoutError:
                continue

            try:
                ticker = candidate.ticker
                ms = self.market_clock.status()

                # Always try to get price + options (even near close — useful for signal mode)
                price = await self.market_data.get_price(ticker)
                if price is None:
                    continue

                await event_bus.emit(
                    "TRIGGER_FETCH", "orchestrator", ticker=ticker,
                    payload={
                        "ticker": ticker, "urgency": candidate.urgency,
                        "cross_tier": candidate.cross_tier_confirmed,
                        "market_status": ms.status_text,
                    },
                )

                # Fetch chain if market is open (or recently closed — IV data still useful)
                contracts = []
                if ms.is_market_open or ms.status_text in ("AFTER_HOURS", "OPEN_NO_NEW_ENTRIES"):
                    contracts = await self.options_chain.fetch_chain(ticker, price, force=True)
                    if contracts:
                        contracts = await self.greeks_calc.compute_for_contracts(contracts, price)

                # Flow detection
                flow_signal = await self.flow_detector.analyze(ticker)
                if flow_signal:
                    db = SessionLocal()
                    try:
                        c = db.query(Candidate).get(candidate.id)
                        if c:
                            c.flow_confirmed = (flow_signal.direction == c.direction)
                            c.flow_score = flow_signal.score
                            if c.flow_confirmed:
                                c.urgency = min(100, c.urgency + 10)
                            db.commit()
                    finally:
                        db.close()

                # Score contracts and emit the signal alert
                best_contract = None
                if contracts:
                    db = SessionLocal()
                    try:
                        cand = db.query(Candidate).get(candidate.id)
                    finally:
                        db.close()
                    if cand:
                        best_contract = await self.options_engine.select_contract(cand, contracts)

                # Emit SIGNAL_ALERT (the key event for signal mode push notifications)
                alert_payload = {
                    "ticker": ticker,
                    "direction": candidate.direction,
                    "urgency": candidate.urgency,
                    "cross_tier_confirmed": candidate.cross_tier_confirmed,
                    "flow_confirmed": getattr(candidate, "flow_confirmed", False),
                    "flow_score": getattr(candidate, "flow_score", 0),
                    "market_status": ms.status_text,
                    "underlying_price": price,
                    "rationale": (candidate.rationale or "")[:400],
                }
                if best_contract:
                    alert_payload["suggested_contract"] = {
                        "symbol": best_contract.contract_symbol,
                        "type": best_contract.option_type,
                        "strike": best_contract.strike,
                        "expiry": best_contract.expiry,
                        "score": best_contract.score,
                        "delta": best_contract.delta,
                        "iv": best_contract.iv,
                        "bid": best_contract.bid,
                        "ask": best_contract.ask,
                    }

                severity = "info"
                if candidate.cross_tier_confirmed:
                    severity = "warning"  # elevated visibility for cross-tier

                await event_bus.emit(
                    "SIGNAL_ALERT", "orchestrator", ticker=ticker,
                    severity=severity, payload=alert_payload,
                )

                # In trade mode, also execute
                if self.mode == "trade" and ms.can_enter_new and best_contract and self.sim_broker:
                    db = SessionLocal()
                    try:
                        cand = db.query(Candidate).get(candidate.id)
                    finally:
                        db.close()
                    if cand:
                        order = await self.risk_engine.plan_order(cand, best_contract)
                        if order:
                            await self.sim_broker.fill_order(order)

            except Exception as exc:
                logger.error("Trigger loop error: %s", exc, exc_info=True)

    # ── Signal mode: off-hours scanning ──

    async def _signal_scan_loop(self) -> None:
        """Signal mode only: emit watch-alerts for off-hours news.

        During market hours, the trigger loop handles it.
        Off-hours, we still run sentiment and emit alerts for pre-market prep.
        """
        logger.info("Signal scan loop started (off-hours alert generation)")
        while self._running:
            try:
                ms = self.market_clock.status()

                if ms.is_market_open:
                    # During market hours, trigger loop handles alerts
                    await asyncio.sleep(60)
                    continue

                # Off-hours: check for any new high-conviction candidates
                db = SessionLocal()
                try:
                    candidates = (
                        db.query(Candidate)
                        .filter(Candidate.status == "active")
                        .order_by(Candidate.urgency.desc())
                        .limit(5)
                        .all()
                    )

                    for c in candidates:
                        if c.urgency >= 50:
                            action = "CALL" if c.direction == "bullish" else "PUT"
                            watch_type = "options" if c.urgency >= 65 else "stock"

                            await event_bus.emit(
                                "WATCH_ALERT", "orchestrator",
                                ticker=c.ticker,
                                severity="warning",
                                payload={
                                    "ticker": c.ticker,
                                    "direction": c.direction,
                                    "action": action,
                                    "watch_type": watch_type,
                                    "urgency": c.urgency,
                                    "cross_tier": c.cross_tier_confirmed,
                                    "rationale": (c.rationale or "")[:400],
                                    "market_status": ms.status_text,
                                    "message": (
                                        f"{'[CROSS-CONFIRMED] ' if c.cross_tier_confirmed else ''}"
                                        f"Watch {c.ticker} for {action} signal at open — "
                                        f"sentiment {c.direction} (urgency {c.urgency:.0f})"
                                    ),
                                },
                            )
                finally:
                    db.close()

            except Exception as exc:
                logger.error("Signal scan error: %s", exc)

            await asyncio.sleep(300)  # every 5 minutes off-hours

    # ── Trade mode: scheduled decision tick ──

    async def _decision_loop(self) -> None:
        """30-minute decision tick: fetch options, score, trade (trade mode only)."""
        logger.info("Decision loop started (interval=%dm)", DECISION_TICK_MINUTES)
        while self._running:
            try:
                ms = self.market_clock.status()
                if not ms.is_market_open:
                    await asyncio.sleep(60)
                    continue
                if not self.market_clock.is_decision_tick(DECISION_TICK_MINUTES):
                    await asyncio.sleep(30)
                    continue

                logger.info("Decision tick at %s (%s)",
                           ms.current_et.strftime("%H:%M"), ms.status_text)

                db = SessionLocal()
                try:
                    cands = (
                        db.query(Candidate)
                        .filter(Candidate.status == "active")
                        .order_by(Candidate.urgency.desc())
                        .all()
                    )
                    cand_data = [
                        {"id": c.id, "ticker": c.ticker,
                         "direction": c.direction, "urgency": c.urgency}
                        for c in cands
                    ]
                finally:
                    db.close()

                new_trades = 0
                for cd in cand_data:
                    if new_trades >= MAX_NEW_TRADES_PER_TICK:
                        break
                    ticker = cd["ticker"]
                    price = await self.market_data.get_price(ticker)
                    if not price:
                        continue
                    contracts = await self.options_chain.fetch_chain(ticker, price)
                    if not contracts:
                        continue
                    contracts = await self.greeks_calc.compute_for_contracts(contracts, price)

                    flow = await self.flow_detector.analyze(ticker)
                    if flow:
                        db = SessionLocal()
                        try:
                            c = db.query(Candidate).get(cd["id"])
                            if c:
                                c.flow_confirmed = flow.direction == c.direction
                                c.flow_score = flow.score
                                db.commit()
                        finally:
                            db.close()

                    db = SessionLocal()
                    try:
                        cand = db.query(Candidate).get(cd["id"])
                        if not cand:
                            continue
                    finally:
                        db.close()

                    best = await self.options_engine.select_contract(cand, contracts)
                    if not best:
                        continue
                    if not ms.can_enter_new:
                        await event_bus.emit(
                            "TRADE_SKIPPED_AFTER_CUTOFF", "orchestrator",
                            ticker=ticker,
                            payload={"ticker": ticker, "reason": ms.status_text})
                        continue
                    order = await self.risk_engine.plan_order(cand, best)
                    if not order:
                        continue
                    if self.sim_broker:
                        fill = await self.sim_broker.fill_order(order)
                        if fill:
                            new_trades += 1

                logger.info("Decision tick complete: %d new trades", new_trades)
            except Exception as exc:
                logger.error("Decision loop error: %s", exc, exc_info=True)

            await asyncio.sleep(DECISION_TICK_MINUTES * 60)

    # ── Position monitoring (trade mode only) ──

    async def _monitor_loop(self) -> None:
        logger.info("Monitor loop started")
        while self._running:
            try:
                if self.sim_broker:
                    await self.sim_broker.mark_to_market()
                    await self.sim_broker.check_exits()
            except Exception as exc:
                logger.error("Monitor loop error: %s", exc)
            await asyncio.sleep(60)

    # ── Clock status ──

    async def _clock_loop(self) -> None:
        while self._running:
            try:
                await self.market_clock.emit_status()
            except Exception as exc:
                logger.error("Clock loop error: %s", exc)
            await asyncio.sleep(300)
