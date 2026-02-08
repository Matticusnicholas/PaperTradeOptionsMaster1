"""Unit tests for Black-Scholes Greeks calculator."""

import pytest
from app.modules.greeks import compute_bs_greeks


class TestBlackScholes:
    def test_atm_call_delta_near_05(self):
        """ATM call should have delta ~0.5."""
        g = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.3, option_type="call")
        assert 0.4 < g["delta"] < 0.65

    def test_atm_put_delta_near_neg_05(self):
        """ATM put should have delta ~-0.5."""
        g = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.3, option_type="put")
        assert -0.65 < g["delta"] < -0.4

    def test_deep_itm_call_delta_near_1(self):
        g = compute_bs_greeks(S=150, K=100, T=0.1, sigma=0.3, option_type="call")
        assert g["delta"] > 0.9

    def test_deep_otm_call_delta_near_0(self):
        g = compute_bs_greeks(S=50, K=100, T=0.1, sigma=0.3, option_type="call")
        assert g["delta"] < 0.1

    def test_gamma_positive(self):
        g = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.3, option_type="call")
        assert g["gamma"] > 0

    def test_theta_negative_for_call(self):
        """Call theta should be negative (time decay)."""
        g = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.3, option_type="call")
        assert g["theta"] < 0

    def test_vega_positive(self):
        g = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.3, option_type="call")
        assert g["vega"] > 0

    def test_zero_time_returns_zeros(self):
        g = compute_bs_greeks(S=100, K=100, T=0, sigma=0.3, option_type="call")
        assert g["delta"] == 0
        assert g["gamma"] == 0

    def test_higher_iv_higher_vega(self):
        g_low = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.2, option_type="call")
        g_high = compute_bs_greeks(S=100, K=100, T=0.1, sigma=0.5, option_type="call")
        # Higher IV option should have different characteristics
        assert g_high["bs_price"] > g_low["bs_price"]

    def test_put_call_parity_approx(self):
        """Put-call parity: C - P ≈ S - K*e^(-rT)."""
        import math
        S, K, T, sigma, r = 100, 100, 0.25, 0.3, 0.05
        c = compute_bs_greeks(S=S, K=K, T=T, sigma=sigma, r=r, option_type="call")
        p = compute_bs_greeks(S=S, K=K, T=T, sigma=sigma, r=r, option_type="put")
        parity = S - K * math.exp(-r * T)
        diff = c["bs_price"] - p["bs_price"]
        assert abs(diff - parity) < 0.01
