"""OptionsEngine – Score and select contracts for a Candidate (Stage 2 decision)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import DELTA_TARGET_MAX, DELTA_TARGET_MIN
from app.database import SessionLocal
from app.models.tables import Candidate, OptionContract
from app.modules.event_bus import event_bus

logger = logging.getLogger("options_engine")


class OptionsEngine:
    """Score option contracts and select the best one for a candidate trade."""

    def __init__(self) -> None:
        self.delta_min = DELTA_TARGET_MIN
        self.delta_max = DELTA_TARGET_MAX

    async def select_contract(
        self, candidate: Candidate, contracts: List[OptionContract]
    ) -> Optional[OptionContract]:
        """Score all contracts and pick the best one for the candidate direction."""
        if not contracts:
            await event_bus.emit(
                "CONTRACT_REJECTED", "options_engine",
                ticker=candidate.ticker,
                payload={
                    "ticker": candidate.ticker,
                    "reason": "no contracts available",
                    "candidate_id": candidate.id,
                },
            )
            return None

        # Filter by option type matching direction
        opt_type = "call" if candidate.direction == "bullish" else "put"
        eligible = [c for c in contracts if c.option_type == opt_type]

        if not eligible:
            await event_bus.emit(
                "CONTRACT_REJECTED", "options_engine",
                ticker=candidate.ticker,
                payload={
                    "ticker": candidate.ticker,
                    "reason": f"no {opt_type} contracts found",
                    "candidate_id": candidate.id,
                },
            )
            return None

        # Score each contract
        scored: List[Tuple[float, OptionContract, Dict]] = []
        for contract in eligible:
            score, breakdown = self._score_contract(contract)
            contract.score = round(score, 4)
            contract.score_breakdown = breakdown
            scored.append((score, contract, breakdown))

        # Persist scores
        db: Session = SessionLocal()
        try:
            for score, contract, breakdown in scored:
                c = db.query(OptionContract).get(contract.id)
                if c:
                    c.score = round(score, 4)
                    c.score_breakdown = breakdown
            db.commit()
        finally:
            db.close()

        await event_bus.emit(
            "CONTRACTS_SCORED", "options_engine",
            ticker=candidate.ticker,
            payload={
                "ticker": candidate.ticker,
                "scored_count": len(scored),
                "candidate_id": candidate.id,
                "top_scores": [
                    {"symbol": c.contract_symbol, "score": round(s, 4), "strike": c.strike, "expiry": c.expiry}
                    for s, c, _ in sorted(scored, key=lambda x: -x[0])[:5]
                ],
            },
        )

        # Select the highest-scoring contract above threshold
        scored.sort(key=lambda x: -x[0])
        best_score, best_contract, best_breakdown = scored[0]

        if best_score < 20:
            await event_bus.emit(
                "CONTRACT_REJECTED", "options_engine",
                ticker=candidate.ticker,
                payload={
                    "ticker": candidate.ticker,
                    "reason": f"best score {best_score:.2f} below threshold 20",
                    "candidate_id": candidate.id,
                    "best_breakdown": best_breakdown,
                },
            )
            return None

        await event_bus.emit(
            "CONTRACT_SELECTED", "options_engine",
            ticker=candidate.ticker,
            payload={
                "ticker": candidate.ticker,
                "candidate_id": candidate.id,
                "contract_symbol": best_contract.contract_symbol,
                "strike": best_contract.strike,
                "expiry": best_contract.expiry,
                "option_type": opt_type,
                "score": round(best_score, 4),
                "breakdown": best_breakdown,
                "delta": best_contract.delta,
                "theta": best_contract.theta,
                "iv": best_contract.iv,
            },
        )

        return best_contract

    def _score_contract(self, c: OptionContract) -> Tuple[float, Dict]:
        """Score a single option contract. Returns (score, breakdown_dict)."""
        score = 0.0
        breakdown: Dict[str, float] = {}

        # 1. Delta alignment (0-30 points)
        delta_abs = abs(c.delta or 0)
        if self.delta_min <= delta_abs <= self.delta_max:
            # In target band = full points
            delta_pts = 30.0
        elif delta_abs < self.delta_min:
            # Too OTM
            delta_pts = max(0, 30 * (delta_abs / self.delta_min))
        else:
            # Too ITM
            overshoot = delta_abs - self.delta_max
            delta_pts = max(0, 30 - overshoot * 40)
        score += delta_pts
        breakdown["delta_alignment"] = round(delta_pts, 2)

        # 2. Theta penalty (0 to -15 points)
        theta_daily = abs(c.theta or 0)
        mid = (c.bid or 0 + (c.ask or 0)) / 2 if (c.bid or 0) > 0 else (c.last_price or 0)
        if mid > 0 and theta_daily > 0:
            theta_ratio = theta_daily / mid  # daily decay as % of premium
            theta_penalty = min(15, theta_ratio * 150)
        else:
            theta_penalty = 5  # unknown = mild penalty
        score -= theta_penalty
        breakdown["theta_penalty"] = round(-theta_penalty, 2)

        # 3. Spread penalty (0 to -15 points)
        bid = c.bid or 0
        ask = c.ask or 0
        if bid > 0 and ask > 0:
            spread = ask - bid
            spread_pct = spread / ((bid + ask) / 2)
            spread_penalty = min(15, spread_pct * 50)
        elif bid == 0 and ask == 0:
            spread_penalty = 10  # no quotes = big penalty
        else:
            spread_penalty = 5
        score -= spread_penalty
        breakdown["spread_penalty"] = round(-spread_penalty, 2)

        # 4. IV regime penalty (0 to -10 points) – avoid buying very high IV
        iv = c.iv or 0
        if iv > 1.0:  # 100% IV
            iv_penalty = min(10, (iv - 1.0) * 20)
        elif iv > 0.6:
            iv_penalty = (iv - 0.6) * 10
        else:
            iv_penalty = 0
        score -= iv_penalty
        breakdown["iv_penalty"] = round(-iv_penalty, 2)

        # 5. Vega/IV value (0-10 points) – higher vega good for near-term catalysts
        vega = abs(c.vega or 0)
        vega_pts = min(10, vega * 5)
        score += vega_pts
        breakdown["vega_score"] = round(vega_pts, 2)

        # 6. Gamma preference for near-term (0-10 points)
        gamma = abs(c.gamma or 0)
        dte = c.dte or 30
        if dte <= 14:
            gamma_pts = min(10, gamma * 200)
        else:
            gamma_pts = min(5, gamma * 100)
        score += gamma_pts
        breakdown["gamma_score"] = round(gamma_pts, 2)

        # 7. Volume / OI liquidity bonus (0-10 points)
        volume = c.volume or 0
        oi = c.open_interest or 0
        liq_pts = min(5, volume / 100) + min(5, oi / 500)
        score += liq_pts
        breakdown["liquidity_bonus"] = round(liq_pts, 2)

        # 8. Cost sanity: penalise very cheap options (< $0.20) or very expensive (> $20)
        premium = mid if mid > 0 else (c.last_price or 0)
        if premium < 0.20:
            score -= 5
            breakdown["cost_penalty"] = -5
        elif premium > 20:
            score -= 3
            breakdown["cost_penalty"] = -3
        else:
            breakdown["cost_penalty"] = 0

        breakdown["total"] = round(score, 2)
        return score, breakdown
