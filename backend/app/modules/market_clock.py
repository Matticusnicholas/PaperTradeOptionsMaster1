"""MarketClock – ET-based trading schedule enforcement."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import NamedTuple

import pytz

from app.config import LAST_ENTRY_TIME_ET, MARKET_CLOSE_ET, MARKET_OPEN_ET
from app.modules.event_bus import event_bus

logger = logging.getLogger("market_clock")

ET = pytz.timezone("America/New_York")


def _parse_time(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


class MarketStatus(NamedTuple):
    is_market_open: bool
    can_enter_new: bool
    is_after_cutoff: bool
    is_after_close: bool
    current_et: datetime
    status_text: str


class MarketClock:
    """Enforces regular market hours and last-entry cutoff rules."""

    def __init__(self) -> None:
        self.open_time = _parse_time(MARKET_OPEN_ET)
        self.close_time = _parse_time(MARKET_CLOSE_ET)
        self.last_entry_time = _parse_time(LAST_ENTRY_TIME_ET)

    def now_et(self) -> datetime:
        return datetime.now(ET)

    def status(self) -> MarketStatus:
        now = self.now_et()
        t = now.time()
        weekday = now.weekday()  # 0=Mon, 6=Sun

        # Weekend check
        if weekday >= 5:
            return MarketStatus(
                is_market_open=False,
                can_enter_new=False,
                is_after_cutoff=True,
                is_after_close=True,
                current_et=now,
                status_text="WEEKEND",
            )

        is_open = self.open_time <= t < self.close_time
        can_enter = is_open and t < self.last_entry_time
        after_cutoff = t >= self.last_entry_time
        after_close = t >= self.close_time

        if not is_open and t < self.open_time:
            text = "PRE_MARKET"
        elif can_enter:
            text = "OPEN_TRADING"
        elif is_open and after_cutoff:
            text = "OPEN_NO_NEW_ENTRIES"
        elif after_close:
            text = "AFTER_HOURS"
        else:
            text = "CLOSED"

        return MarketStatus(
            is_market_open=is_open,
            can_enter_new=can_enter,
            is_after_cutoff=after_cutoff,
            is_after_close=after_close,
            current_et=now,
            status_text=text,
        )

    def is_decision_tick(self, tick_minutes: int = 30) -> bool:
        """Check if current time is on a decision tick boundary."""
        now = self.now_et()
        return now.minute % tick_minutes < 2  # 2-min grace window

    async def emit_status(self) -> MarketStatus:
        ms = self.status()
        await event_bus.emit(
            "MARKET_CLOCK_STATUS", "market_clock",
            payload={
                "status": ms.status_text,
                "is_market_open": ms.is_market_open,
                "can_enter_new": ms.can_enter_new,
                "is_after_cutoff": ms.is_after_cutoff,
                "current_et": ms.current_et.isoformat(),
            },
        )
        return ms
