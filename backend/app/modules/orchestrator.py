"""Orchestrator – main trading loop that coordinates all modules."""

from __future__ import annotations

import asyncio
import logging
from typing import List

from app.config import (
    DECISION_TICK_MINUTES,
    MAX_NEW_TRADES_PER_TICK,
    NEWS_POLL_SECONDS,
)
from app.models.tables import Candidate, NewsItem
from app.modules.candidate_funnel import CandidateFunnel
from app.modules.coverage_tracker import CoverageIntensityTracker
from app.modules.event_bus import event_bus
from app.modules.greeks import GreeksCalculator
from app.modules.market_clock import MarketClock
from app.modules.market_data import MarketDataProvider
from app.modules.news_ingestor import NewsIngestor
from app.modules.options_chain import OptionsChainProvider
from app.modules.options_engine import OptionsEngine
from app.modules.risk_engine import RiskEngine
from app.modules.sentiment_engine import AnalystStyleSentimentEngine
from app.modules.sim_broker import SimBroker
from app.modules.ticker_resolver import TickerResolver

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """Coordinates all pipeline stages in async background loops."""

    def __init__(self) -> None:
        self.news_ingestor = NewsIngestor()
        self.ticker_resolver = TickerResolver()
        self.sentiment_engine = AnalystStyleSentimentEngine()
        self.coverage_tracker = CoverageIntensityTracker()
        self.candidate_funnel = CandidateFunnel()
        self.market_data = MarketDataProvider()
        self.options_chain = OptionsChainProvider()
        self.greeks_calc = GreeksCalculator()
        self.options_engine = OptionsEngine()
        self.risk_engine = RiskEngine()
        self.sim_broker = SimBroker(self.market_data)
        self.market_clock = MarketClock()
        self._running = False

    async def start(self) -> None:
        """Start all background loops."""
        self._running = True
        logger.info("Orchestrator starting all loops...")

        await event_bus.emit(
            "MARKET_CLOCK_STATUS", "orchestrator",
            payload={"message": "Orchestrator starting"},
        )

        # Launch concurrent loops
        await asyncio.gather(
            self._news_loop(),
            self._decision_loop(),
            self._monitor_loop(),
            self._clock_loop(),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        self._running = False

    # ── Stage 1: News → Sentiment → Coverage → Candidates ──

    async def _news_loop(self) -> None:
        """Continuously ingest news and run Stage 1 pipeline."""
        logger.info("News loop started (interval=%ds)", NEWS_POLL_SECONDS)
        while self._running:
            try:
                # 1. Poll RSS
                new_items: List[NewsItem] = await self.news_ingestor.poll_once()

                # 2. Resolve tickers for each new item
                affected_tickers = set()
                for item in new_items:
                    mentions = await self.ticker_resolver.resolve(item)
                    for mention in mentions:
                        # 3. Score sentiment
                        await self.sentiment_engine.analyze_news(item, mention.ticker)
                        affected_tickers.add(mention.ticker)

                # 4. Update coverage for affected tickers
                for ticker in affected_tickers:
                    await self.coverage_tracker.update(ticker)

                # 5. Run candidate funnel
                if affected_tickers:
                    await self.candidate_funnel.evaluate()

            except Exception as exc:
                logger.error("News loop error: %s", exc, exc_info=True)
                await event_bus.emit(
                    "ERROR", "orchestrator",
                    severity="error",
                    payload={"loop": "news", "error": str(exc)},
                )

            await asyncio.sleep(NEWS_POLL_SECONDS)

    # ── Stage 2: Options evaluation + trading ──

    async def _decision_loop(self) -> None:
        """30-minute decision tick: fetch options, score, trade."""
        logger.info("Decision loop started (interval=%dm)", DECISION_TICK_MINUTES)
        while self._running:
            try:
                ms = self.market_clock.status()

                if not ms.is_market_open:
                    logger.debug("Market closed (%s), skipping decision tick", ms.status_text)
                    await asyncio.sleep(60)
                    continue

                # Check if it's a decision tick
                if not self.market_clock.is_decision_tick(DECISION_TICK_MINUTES):
                    await asyncio.sleep(30)
                    continue

                logger.info("Decision tick firing at %s (status=%s)",
                           ms.current_et.strftime("%H:%M"), ms.status_text)

                # Get active candidates
                from app.database import SessionLocal
                from app.models.tables import Candidate
                db = SessionLocal()
                try:
                    candidates = (
                        db.query(Candidate)
                        .filter(Candidate.status == "active")
                        .order_by(Candidate.urgency.desc())
                        .all()
                    )
                    # Detach from session
                    candidate_data = [
                        {
                            "id": c.id, "ticker": c.ticker,
                            "direction": c.direction, "urgency": c.urgency,
                        }
                        for c in candidates
                    ]
                finally:
                    db.close()

                new_trades = 0
                for cdata in candidate_data:
                    if new_trades >= MAX_NEW_TRADES_PER_TICK:
                        break

                    ticker = cdata["ticker"]

                    # Get underlying price
                    price = await self.market_data.get_price(ticker)
                    if price is None:
                        continue

                    # Fetch options chain (respects throttle)
                    contracts = await self.options_chain.fetch_chain(ticker, price)
                    if not contracts:
                        continue

                    # Compute Greeks
                    contracts = await self.greeks_calc.compute_for_contracts(contracts, price)

                    # Re-load candidate from DB
                    db = SessionLocal()
                    try:
                        candidate = db.query(Candidate).get(cdata["id"])
                        if not candidate:
                            continue
                    finally:
                        db.close()

                    # Select best contract
                    best = await self.options_engine.select_contract(candidate, contracts)
                    if not best:
                        continue

                    # Check if we can enter new trades
                    if not ms.can_enter_new:
                        await event_bus.emit(
                            "TRADE_SKIPPED_AFTER_CUTOFF", "orchestrator",
                            ticker=ticker,
                            payload={
                                "ticker": ticker,
                                "reason": f"After cutoff ({ms.status_text})",
                                "contract": best.contract_symbol,
                            },
                        )
                        continue

                    # Plan order
                    order = await self.risk_engine.plan_order(candidate, best)
                    if not order:
                        continue

                    # Fill order
                    fill = await self.sim_broker.fill_order(order)
                    if fill:
                        new_trades += 1

                logger.info("Decision tick complete: %d new trades", new_trades)

            except Exception as exc:
                logger.error("Decision loop error: %s", exc, exc_info=True)
                await event_bus.emit(
                    "ERROR", "orchestrator",
                    severity="error",
                    payload={"loop": "decision", "error": str(exc)},
                )

            # Wait until next tick boundary
            await asyncio.sleep(DECISION_TICK_MINUTES * 60)

    # ── Position monitoring ──

    async def _monitor_loop(self) -> None:
        """Check exits and mark-to-market every 60 seconds."""
        logger.info("Monitor loop started")
        while self._running:
            try:
                await self.sim_broker.mark_to_market()
                await self.sim_broker.check_exits()
            except Exception as exc:
                logger.error("Monitor loop error: %s", exc)
            await asyncio.sleep(60)

    # ── Clock status ──

    async def _clock_loop(self) -> None:
        """Emit market clock status periodically."""
        while self._running:
            try:
                await self.market_clock.emit_status()
            except Exception as exc:
                logger.error("Clock loop error: %s", exc)
            await asyncio.sleep(300)  # every 5 minutes
