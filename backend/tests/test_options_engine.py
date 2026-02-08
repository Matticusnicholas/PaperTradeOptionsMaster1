"""Unit tests for OptionsEngine contract scoring."""

import pytest
from unittest.mock import MagicMock
from app.modules.options_engine import OptionsEngine


@pytest.fixture
def engine():
    return OptionsEngine()


def _make_contract(**kwargs):
    """Create a mock OptionContract."""
    defaults = {
        "id": 1,
        "ticker": "AAPL",
        "contract_symbol": "AAPL250117C00200000",
        "option_type": "call",
        "strike": 200.0,
        "expiry": "2025-01-17",
        "bid": 5.0,
        "ask": 5.50,
        "last_price": 5.25,
        "volume": 500,
        "open_interest": 2000,
        "iv": 0.35,
        "delta": 0.55,
        "gamma": 0.02,
        "theta": -0.05,
        "vega": 0.15,
        "dte": 10,
        "moneyness": 1.0,
        "score": None,
        "score_breakdown": None,
    }
    defaults.update(kwargs)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestContractScoring:
    def test_ideal_contract_scores_well(self, engine):
        """A contract in the ideal delta range with good liquidity should score well."""
        c = _make_contract(delta=0.55, bid=5.0, ask=5.50, iv=0.35, dte=10)
        score, breakdown = engine._score_contract(c)
        assert score > 20  # Above selection threshold
        assert breakdown["delta_alignment"] > 20

    def test_low_delta_penalized(self, engine):
        """Very OTM (low delta) should score worse."""
        c_ideal = _make_contract(delta=0.55)
        c_otm = _make_contract(delta=0.10)
        s_ideal, _ = engine._score_contract(c_ideal)
        s_otm, _ = engine._score_contract(c_otm)
        assert s_ideal > s_otm

    def test_high_delta_penalized(self, engine):
        """Very ITM (high delta) should score worse than ideal."""
        c_ideal = _make_contract(delta=0.55)
        c_itm = _make_contract(delta=0.95)
        s_ideal, _ = engine._score_contract(c_ideal)
        s_itm, _ = engine._score_contract(c_itm)
        assert s_ideal > s_itm

    def test_wide_spread_penalized(self, engine):
        """Wide bid-ask spread should be penalized."""
        c_tight = _make_contract(bid=5.0, ask=5.20)
        c_wide = _make_contract(bid=4.0, ask=7.0)
        s_tight, _ = engine._score_contract(c_tight)
        s_wide, _ = engine._score_contract(c_wide)
        assert s_tight > s_wide

    def test_high_iv_penalized(self, engine):
        """Very high IV (>100%) should be penalized."""
        c_normal = _make_contract(iv=0.35)
        c_high_iv = _make_contract(iv=1.5)
        s_normal, _ = engine._score_contract(c_normal)
        s_high, _ = engine._score_contract(c_high_iv)
        assert s_normal > s_high

    def test_no_quotes_penalized(self, engine):
        """Zero bid/ask should get spread penalty."""
        c = _make_contract(bid=0, ask=0, last_price=5.0)
        _, breakdown = engine._score_contract(c)
        assert breakdown["spread_penalty"] < 0

    def test_cheap_option_penalized(self, engine):
        """Very cheap options (<$0.20) penalized."""
        c = _make_contract(bid=0.05, ask=0.10, last_price=0.08)
        _, breakdown = engine._score_contract(c)
        assert breakdown["cost_penalty"] < 0

    def test_good_liquidity_bonus(self, engine):
        """High volume and OI should get a bonus."""
        c_liquid = _make_contract(volume=1000, open_interest=5000)
        c_illiquid = _make_contract(volume=5, open_interest=10)
        s_liq, _ = engine._score_contract(c_liquid)
        s_illiq, _ = engine._score_contract(c_illiquid)
        assert s_liq > s_illiq

    def test_score_breakdown_has_total(self, engine):
        c = _make_contract()
        _, breakdown = engine._score_contract(c)
        assert "total" in breakdown
        assert "delta_alignment" in breakdown
        assert "theta_penalty" in breakdown
        assert "spread_penalty" in breakdown
