"""FlowDetector – detect unusual options activity (volume/OI spikes) as institutional signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import FLOW_OI_SPIKE_MULTIPLIER, FLOW_VOLUME_SPIKE_MULTIPLIER
from app.database import SessionLocal
from app.models.tables import OptionContract
from app.modules.event_bus import event_bus

logger = logging.getLogger("flow_detector")


class FlowSignal:
    """Represents a detected unusual flow signal."""

    def __init__(
        self,
        ticker: str,
        direction: str,  # bullish / bearish / mixed
        score: float,  # 0-100
        call_volume_ratio: float,
        put_volume_ratio: float,
        call_oi_ratio: float,
        put_oi_ratio: float,
        top_contracts: List[Dict],
        explanation: str,
    ):
        self.ticker = ticker
        self.direction = direction
        self.score = score
        self.call_volume_ratio = call_volume_ratio
        self.put_volume_ratio = put_volume_ratio
        self.call_oi_ratio = call_oi_ratio
        self.put_oi_ratio = put_oi_ratio
        self.top_contracts = top_contracts
        self.explanation = explanation


class FlowDetector:
    """Detect unusual options activity that may indicate institutional positioning.

    Compares current snapshot volume/OI against historical baselines.
    When volume is N*X above normal on calls vs puts, signals direction.
    """

    def __init__(self) -> None:
        self.volume_spike_mult = FLOW_VOLUME_SPIKE_MULTIPLIER
        self.oi_spike_mult = FLOW_OI_SPIKE_MULTIPLIER
        # In-memory baselines: ticker -> {avg_call_vol, avg_put_vol, avg_call_oi, avg_put_oi}
        self._baselines: Dict[str, Dict[str, float]] = {}

    async def analyze(self, ticker: str) -> Optional[FlowSignal]:
        """Analyze latest options data for unusual activity."""
        db: Session = SessionLocal()
        try:
            # Get the most recent contracts for this ticker
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            recent = (
                db.query(OptionContract)
                .filter(
                    OptionContract.ticker == ticker,
                    OptionContract.id > self._get_min_id(db, ticker, cutoff),
                )
                .all()
            )

            if not recent:
                return None

            # Aggregate current snapshot
            call_vol = sum(c.volume or 0 for c in recent if c.option_type == "call")
            put_vol = sum(c.volume or 0 for c in recent if c.option_type == "put")
            call_oi = sum(c.open_interest or 0 for c in recent if c.option_type == "call")
            put_oi = sum(c.open_interest or 0 for c in recent if c.option_type == "put")

            # Get or build baseline
            baseline = self._baselines.get(ticker)
            if not baseline:
                baseline = await self._compute_baseline(db, ticker)
                self._baselines[ticker] = baseline

            if not baseline or baseline.get("avg_call_vol", 0) == 0:
                # First time seeing this ticker, store current as baseline
                self._baselines[ticker] = {
                    "avg_call_vol": max(call_vol, 1),
                    "avg_put_vol": max(put_vol, 1),
                    "avg_call_oi": max(call_oi, 1),
                    "avg_put_oi": max(put_oi, 1),
                }
                return None

            # Compute ratios vs baseline
            call_vol_ratio = call_vol / max(baseline["avg_call_vol"], 1)
            put_vol_ratio = put_vol / max(baseline["avg_put_vol"], 1)
            call_oi_ratio = call_oi / max(baseline["avg_call_oi"], 1)
            put_oi_ratio = put_oi / max(baseline["avg_put_oi"], 1)

            # Detect spikes
            call_vol_spike = call_vol_ratio >= self.volume_spike_mult
            put_vol_spike = put_vol_ratio >= self.volume_spike_mult
            call_oi_spike = call_oi_ratio >= self.oi_spike_mult
            put_oi_spike = put_oi_ratio >= self.oi_spike_mult

            has_signal = call_vol_spike or put_vol_spike or call_oi_spike or put_oi_spike
            if not has_signal:
                return None

            # Determine direction
            explanation_parts = []
            direction, score = self._determine_direction(
                call_vol_ratio, put_vol_ratio,
                call_oi_ratio, put_oi_ratio,
                call_vol_spike, put_vol_spike,
                call_oi_spike, put_oi_spike,
                explanation_parts,
            )

            # Find top unusual contracts
            top_contracts = self._find_top_contracts(recent)

            explanation = "; ".join(explanation_parts)

            signal = FlowSignal(
                ticker=ticker,
                direction=direction,
                score=score,
                call_volume_ratio=round(call_vol_ratio, 2),
                put_volume_ratio=round(put_vol_ratio, 2),
                call_oi_ratio=round(call_oi_ratio, 2),
                put_oi_ratio=round(put_oi_ratio, 2),
                top_contracts=top_contracts,
                explanation=explanation,
            )

            # Update baseline with exponential moving average
            alpha = 0.2
            self._baselines[ticker] = {
                "avg_call_vol": baseline["avg_call_vol"] * (1 - alpha) + call_vol * alpha,
                "avg_put_vol": baseline["avg_put_vol"] * (1 - alpha) + put_vol * alpha,
                "avg_call_oi": baseline["avg_call_oi"] * (1 - alpha) + call_oi * alpha,
                "avg_put_oi": baseline["avg_put_oi"] * (1 - alpha) + put_oi * alpha,
            }

            await event_bus.emit(
                "FLOW_DETECTED", "flow_detector",
                ticker=ticker,
                payload={
                    "ticker": ticker,
                    "direction": direction,
                    "flow_score": round(score, 2),
                    "call_vol_ratio": round(call_vol_ratio, 2),
                    "put_vol_ratio": round(put_vol_ratio, 2),
                    "call_oi_ratio": round(call_oi_ratio, 2),
                    "put_oi_ratio": round(put_oi_ratio, 2),
                    "top_contracts": top_contracts[:3],
                    "explanation": explanation[:300],
                },
            )

            return signal

        finally:
            db.close()

    def _get_min_id(self, db: Session, ticker: str, cutoff: datetime) -> int:
        """Get minimum contract ID for recent window."""
        result = (
            db.query(func.min(OptionContract.id))
            .join(
                # Approximate by looking at recent IDs
            )
            .filter(OptionContract.ticker == ticker)
            .scalar()
        )
        return result or 0

    async def _compute_baseline(self, db: Session, ticker: str) -> Dict[str, float]:
        """Compute baseline volume/OI from historical data."""
        # Use all historical data for this ticker as baseline
        all_contracts = (
            db.query(OptionContract)
            .filter(OptionContract.ticker == ticker)
            .all()
        )
        if not all_contracts:
            return {}

        # Group by snapshot and average across snapshots
        call_vols, put_vols, call_ois, put_ois = [], [], [], []

        call_contracts = [c for c in all_contracts if c.option_type == "call"]
        put_contracts = [c for c in all_contracts if c.option_type == "put"]

        call_vol_total = sum(c.volume or 0 for c in call_contracts)
        put_vol_total = sum(c.volume or 0 for c in put_contracts)
        call_oi_total = sum(c.open_interest or 0 for c in call_contracts)
        put_oi_total = sum(c.open_interest or 0 for c in put_contracts)

        n_snapshots = max(1, len(set(c.snapshot_id for c in all_contracts)))

        return {
            "avg_call_vol": call_vol_total / n_snapshots,
            "avg_put_vol": put_vol_total / n_snapshots,
            "avg_call_oi": call_oi_total / n_snapshots,
            "avg_put_oi": put_oi_total / n_snapshots,
        }

    def _determine_direction(
        self,
        call_vol_r: float, put_vol_r: float,
        call_oi_r: float, put_oi_r: float,
        call_vol_spike: bool, put_vol_spike: bool,
        call_oi_spike: bool, put_oi_spike: bool,
        explanation: List[str],
    ) -> Tuple[str, float]:
        """Determine direction and score from flow ratios."""
        bullish_signals = 0
        bearish_signals = 0
        score = 0.0

        if call_vol_spike:
            bullish_signals += 1
            score += min(30, call_vol_r * 8)
            explanation.append(f"CALL volume {call_vol_r:.1f}x baseline (spike)")

        if put_vol_spike:
            bearish_signals += 1
            score += min(30, put_vol_r * 8)
            explanation.append(f"PUT volume {put_vol_r:.1f}x baseline (spike)")

        if call_oi_spike:
            bullish_signals += 1
            score += min(20, call_oi_r * 6)
            explanation.append(f"CALL OI {call_oi_r:.1f}x baseline (spike)")

        if put_oi_spike:
            bearish_signals += 1
            score += min(20, put_oi_r * 6)
            explanation.append(f"PUT OI {put_oi_r:.1f}x baseline (spike)")

        # Direction based on which side is spiking more
        if bullish_signals > bearish_signals:
            direction = "bullish"
            # Bonus for call-heavy flow
            if call_vol_r > put_vol_r * 1.5:
                score += 15
                explanation.append("Call/Put volume ratio heavily skewed bullish")
        elif bearish_signals > bullish_signals:
            direction = "bearish"
            if put_vol_r > call_vol_r * 1.5:
                score += 15
                explanation.append("Put/Call volume ratio heavily skewed bearish")
        else:
            direction = "mixed"
            score *= 0.5  # Discount mixed signals
            explanation.append("Mixed flow signals (both calls and puts spiking)")

        return direction, min(100.0, score)

    def _find_top_contracts(self, contracts: List[OptionContract]) -> List[Dict]:
        """Find contracts with highest unusual volume."""
        scored = []
        for c in contracts:
            vol = c.volume or 0
            oi = c.open_interest or 0
            if vol == 0:
                continue
            # Volume/OI ratio signals new positions being opened
            vol_oi_ratio = vol / max(oi, 1)
            scored.append({
                "symbol": c.contract_symbol,
                "type": c.option_type,
                "strike": c.strike,
                "expiry": c.expiry,
                "volume": vol,
                "open_interest": oi,
                "vol_oi_ratio": round(vol_oi_ratio, 2),
                "iv": round(c.iv or 0, 4),
            })

        scored.sort(key=lambda x: x["volume"], reverse=True)
        return scored[:5]
