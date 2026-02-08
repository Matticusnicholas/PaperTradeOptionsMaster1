"""RiskEngine – position sizing, profit targets, stops, order planning."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import (
    MAX_OPEN_POSITIONS,
    PER_TICKER_MAX_POSITIONS,
    PROFIT_TARGET_PCT,
    RISK_PER_TRADE_PCT,
    SLIPPAGE_PCT,
    STOP_LOSS_PCT,
    TIME_STOP_HOURS,
)
from app.database import SessionLocal
from app.models.tables import AccountState, Candidate, OptionContract, Order, Position
from app.modules.event_bus import event_bus

logger = logging.getLogger("risk_engine")


class RiskEngine:
    """Produce an OrderPlan: sizing, entry, targets, stops."""

    def __init__(self) -> None:
        self.risk_pct = RISK_PER_TRADE_PCT
        self.profit_target_pct = PROFIT_TARGET_PCT
        self.stop_loss_pct = STOP_LOSS_PCT
        self.time_stop_hours = TIME_STOP_HOURS
        self.max_open = MAX_OPEN_POSITIONS
        self.per_ticker_max = PER_TICKER_MAX_POSITIONS
        self.slippage_pct = SLIPPAGE_PCT

    async def plan_order(
        self,
        candidate: Candidate,
        contract: OptionContract,
    ) -> Optional[Order]:
        """Create an order plan if risk checks pass."""
        db: Session = SessionLocal()
        try:
            # Get account state
            account = db.query(AccountState).order_by(AccountState.id.desc()).first()
            if not account:
                logger.error("No account state found")
                return None

            # Check max open positions
            open_count = (
                db.query(Position)
                .filter(Position.status == "open")
                .count()
            )
            if open_count >= self.max_open:
                await event_bus.emit(
                    "TRADE_SKIPPED_OUTSIDE_HOURS", "risk_engine",
                    ticker=candidate.ticker,
                    payload={
                        "reason": f"max open positions reached ({open_count}/{self.max_open})",
                        "ticker": candidate.ticker,
                    },
                )
                return None

            # Check per-ticker cap
            ticker_positions = (
                db.query(Position)
                .filter(
                    Position.ticker == candidate.ticker,
                    Position.status == "open",
                )
                .count()
            )
            if ticker_positions >= self.per_ticker_max:
                await event_bus.emit(
                    "TRADE_SKIPPED_OUTSIDE_HOURS", "risk_engine",
                    ticker=candidate.ticker,
                    payload={
                        "reason": f"per-ticker position cap ({ticker_positions}/{self.per_ticker_max})",
                        "ticker": candidate.ticker,
                    },
                )
                return None

            # Entry price model: mid + slippage
            bid = contract.bid or 0
            ask = contract.ask or 0
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
            else:
                mid = contract.last_price or 0

            if mid <= 0:
                logger.warning("Cannot determine entry price for %s", contract.contract_symbol)
                return None

            entry_price = mid * (1 + self.slippage_pct)  # buying: pay a bit above mid

            # Position sizing: risk X% of equity
            risk_amount = account.equity * self.risk_pct
            max_loss_per_contract = entry_price * self.stop_loss_pct * 100  # per 1 contract (100 shares)
            if max_loss_per_contract <= 0:
                return None

            quantity = max(1, int(risk_amount / max_loss_per_contract))
            # Cap by available cash
            cost = entry_price * 100 * quantity
            while cost > account.cash * 0.5 and quantity > 1:
                quantity -= 1
                cost = entry_price * 100 * quantity

            if cost > account.cash:
                logger.info("Not enough cash for %s (need $%.2f, have $%.2f)",
                           contract.contract_symbol, cost, account.cash)
                return None

            # Targets
            profit_target = entry_price * (1 + self.profit_target_pct)
            stop_loss = entry_price * (1 - self.stop_loss_pct)
            now = datetime.now(timezone.utc)
            time_stop_at = now + timedelta(hours=self.time_stop_hours)

            rationale = (
                f"Candidate: {candidate.direction} {candidate.ticker} "
                f"(urgency={candidate.urgency:.1f}) | "
                f"Contract: {contract.contract_symbol} "
                f"strike={contract.strike} exp={contract.expiry} | "
                f"Entry={entry_price:.2f} qty={quantity} "
                f"PT={profit_target:.2f} SL={stop_loss:.2f}"
            )

            order = Order(
                ticker=candidate.ticker,
                candidate_id=candidate.id,
                contract_id=contract.id,
                contract_symbol=contract.contract_symbol,
                option_type=contract.option_type,
                strike=contract.strike,
                expiry=contract.expiry,
                direction="buy",
                quantity=quantity,
                limit_price=round(entry_price, 2),
                status="pending",
                profit_target=round(profit_target, 2),
                stop_loss=round(stop_loss, 2),
                time_stop_at=time_stop_at,
                rationale=rationale,
            )
            db.add(order)
            db.commit()
            db.refresh(order)

            await event_bus.emit(
                "ORDER_PLANNED", "risk_engine",
                ticker=candidate.ticker,
                payload={
                    "order_id": order.id,
                    "ticker": candidate.ticker,
                    "contract": contract.contract_symbol,
                    "entry_price": round(entry_price, 2),
                    "quantity": quantity,
                    "profit_target": round(profit_target, 2),
                    "stop_loss": round(stop_loss, 2),
                    "time_stop_hours": self.time_stop_hours,
                    "cost": round(cost, 2),
                    "rationale": rationale[:300],
                },
            )
            return order
        finally:
            db.close()
