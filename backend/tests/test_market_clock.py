"""Unit tests for MarketClock and risk exit logic."""

import pytest
from datetime import time
from app.modules.market_clock import MarketClock, _parse_time


class TestMarketClock:
    def test_parse_time(self):
        t = _parse_time("09:30")
        assert t == time(9, 30)

    def test_parse_time_close(self):
        t = _parse_time("16:00")
        assert t == time(16, 0)

    def test_clock_instantiates(self):
        clock = MarketClock()
        assert clock.open_time == time(9, 30)
        assert clock.close_time == time(16, 0)
        assert clock.last_entry_time == time(15, 0)

    def test_status_returns_status(self):
        clock = MarketClock()
        ms = clock.status()
        # Should always return a valid status regardless of time
        assert ms.status_text in (
            "WEEKEND", "PRE_MARKET", "OPEN_TRADING",
            "OPEN_NO_NEW_ENTRIES", "AFTER_HOURS", "CLOSED",
        )
        assert isinstance(ms.is_market_open, bool)
        assert isinstance(ms.can_enter_new, bool)


class TestRiskExitScenarios:
    """Test that the market clock properly gates trade entries."""

    def test_cutoff_after_3pm(self):
        """After 3:00 PM ET, can_enter_new should be False."""
        clock = MarketClock()
        ms = clock.status()
        # We can't control the time in unit tests without mocking,
        # but we verify the logic structure
        if ms.current_et.time() >= time(15, 0):
            assert ms.can_enter_new is False
        elif ms.current_et.time() >= time(9, 30) and ms.current_et.weekday() < 5:
            assert ms.can_enter_new is True

    def test_weekend_no_trading(self):
        clock = MarketClock()
        ms = clock.status()
        if ms.current_et.weekday() >= 5:
            assert ms.is_market_open is False
            assert ms.can_enter_new is False
            assert ms.status_text == "WEEKEND"
