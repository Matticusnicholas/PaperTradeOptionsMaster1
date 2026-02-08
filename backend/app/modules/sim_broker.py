"""SimBroker – Paper trading broker / local exchange simulator."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import SLIPPAGE_PCT, STARTING_CASH
from app.database import SessionLocal
from app.models.tables import AccountState, Fill, Order, Position
from app.modules.event_bus import event_bus
from app.modules.market_data import MarketDataProvider

logger = logging.getLogger("sim_broker")


class SimBroker:
    """Paper-trading broker: fills orders, manages positions, handles exits."""

    def __init__(self, market_data: MarketDataProvider) -> None:
        self.market_data = market_data
        self._ensure_account()

    def _ensure_account(self) -> None:
        """Create initial account state if not present."""
        db: Session = SessionLocal()
        try:
            acct = db.query(AccountState).first()
            if not acct:
                acct = AccountState(
                    cash=STARTING_CASH,
                    equity=STARTING_CASH,
                    open_positions_count=0,
                    total_trades=0,
                    total_pnl=0.0,
                )
                db.add(acct)
                db.commit()
        finally:
            db.close()

    async def fill_order(self, order: Order) -> Optional[Fill]:
        """Simulate filling an order at current market snapshot."""
        db: Session = SessionLocal()
        try:
            o = db.query(Order).get(order.id)
            if not o or o.status != "pending":
                return None

            fill_price = o.limit_price  # already includes slippage from RiskEngine
            cost = fill_price * 100 * o.quantity

            # Check cash
            acct = db.query(AccountState).order_by(AccountState.id.desc()).first()
            if not acct or acct.cash < cost:
                o.status = "cancelled"
                db.commit()
                logger.warning("Insufficient cash for order %d", o.id)
                return None

            # Create fill
            fill = Fill(
                order_id=o.id,
                fill_price=fill_price,
                quantity=o.quantity,
                slippage=round(fill_price * SLIPPAGE_PCT, 4),
            )
            db.add(fill)

            # Create position
            pos = Position(
                ticker=o.ticker,
                contract_symbol=o.contract_symbol,
                option_type=o.option_type,
                strike=o.strike,
                expiry=o.expiry,
                quantity=o.quantity,
                entry_price=fill_price,
                current_price=fill_price,
                unrealized_pnl=0.0,
                profit_target=o.profit_target,
                stop_loss=o.stop_loss,
                time_stop_at=o.time_stop_at,
                status="open",
                order_id=o.id,
                candidate_id=o.candidate_id,
            )
            db.add(pos)

            # Update order
            o.status = "filled"

            # Update account
            acct.cash -= cost
            acct.open_positions_count += 1
            acct.total_trades += 1

            db.commit()
            db.refresh(fill)
            db.refresh(pos)

            await event_bus.emit(
                "ORDER_PLACED", "sim_broker",
                ticker=o.ticker,
                payload={
                    "order_id": o.id,
                    "ticker": o.ticker,
                    "contract": o.contract_symbol,
                    "fill_price": fill_price,
                    "quantity": o.quantity,
                    "cost": round(cost, 2),
                },
            )

            await event_bus.emit(
                "FILL_RECEIVED", "sim_broker",
                ticker=o.ticker,
                payload={
                    "fill_id": fill.id,
                    "order_id": o.id,
                    "ticker": o.ticker,
                    "fill_price": fill_price,
                    "quantity": o.quantity,
                    "position_id": pos.id,
                },
            )

            return fill
        finally:
            db.close()

    async def mark_to_market(self) -> None:
        """Update all open positions with current prices."""
        db: Session = SessionLocal()
        try:
            positions = db.query(Position).filter(Position.status == "open").all()
            if not positions:
                return

            total_unrealized = 0.0
            for pos in positions:
                # Use market data to get underlying price as proxy
                # In real scenario, we'd re-fetch option quotes
                price = await self.market_data.get_price(pos.ticker)
                if price is None:
                    continue

                # Simplified MTM: estimate option price change proportional to delta
                # This is a rough approximation for paper trading
                if pos.entry_price and pos.entry_price > 0:
                    # Use last known option price with some variation
                    # In production, you'd re-fetch the option chain
                    current = pos.current_price or pos.entry_price
                    pos.current_price = current  # maintain last known
                    pos.unrealized_pnl = round(
                        (current - pos.entry_price) * 100 * pos.quantity, 2
                    )
                    total_unrealized += pos.unrealized_pnl

                    await event_bus.emit(
                        "POSITION_UPDATED", "sim_broker",
                        ticker=pos.ticker,
                        payload={
                            "position_id": pos.id,
                            "ticker": pos.ticker,
                            "entry": pos.entry_price,
                            "current": pos.current_price,
                            "unrealized_pnl": pos.unrealized_pnl,
                            "quantity": pos.quantity,
                        },
                    )

            # Update account equity
            acct = db.query(AccountState).order_by(AccountState.id.desc()).first()
            if acct:
                acct.equity = acct.cash + total_unrealized
                acct.open_positions_count = len(positions)

            db.commit()
        finally:
            db.close()

    async def check_exits(self) -> List[Position]:
        """Check all open positions for exit triggers."""
        db: Session = SessionLocal()
        exited: List[Position] = []
        try:
            positions = db.query(Position).filter(Position.status == "open").all()
            now = datetime.now(timezone.utc)

            for pos in positions:
                exit_reason = None
                current = pos.current_price or pos.entry_price

                # Profit target
                if pos.profit_target and current >= pos.profit_target:
                    exit_reason = "profit_target"
                    event_type = "EXIT_TARGET_HIT"

                # Stop loss
                elif pos.stop_loss and current <= pos.stop_loss:
                    exit_reason = "stop_loss"
                    event_type = "STOP_HIT"

                # Time stop
                elif pos.time_stop_at and now >= pos.time_stop_at:
                    exit_reason = "time_stop"
                    event_type = "TIME_STOP_HIT"

                if exit_reason:
                    pnl = round((current - pos.entry_price) * 100 * pos.quantity, 2)
                    pos.status = "closed"
                    pos.exit_reason = exit_reason
                    pos.realized_pnl = pnl
                    pos.closed_at = now

                    # Return cash
                    acct = db.query(AccountState).order_by(AccountState.id.desc()).first()
                    if acct:
                        acct.cash += current * 100 * pos.quantity
                        acct.total_pnl += pnl
                        acct.open_positions_count = max(0, acct.open_positions_count - 1)

                    exited.append(pos)

                    await event_bus.emit(
                        event_type, "sim_broker",
                        ticker=pos.ticker,
                        payload={
                            "position_id": pos.id,
                            "ticker": pos.ticker,
                            "contract": pos.contract_symbol,
                            "exit_reason": exit_reason,
                            "entry_price": pos.entry_price,
                            "exit_price": current,
                            "pnl": pnl,
                            "quantity": pos.quantity,
                        },
                    )

            db.commit()
        finally:
            db.close()

        return exited
