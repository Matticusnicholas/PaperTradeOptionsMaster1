"""Black-Scholes Greeks calculator (local computation)."""

from __future__ import annotations

import logging
import math
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.tables import OptionContract
from app.modules.event_bus import event_bus

logger = logging.getLogger("greeks")

# Risk-free rate approximation
RISK_FREE_RATE = 0.05


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def compute_bs_greeks(
    S: float,       # underlying price
    K: float,       # strike
    T: float,       # time to expiry in years
    sigma: float,   # implied volatility
    r: float = RISK_FREE_RATE,
    option_type: str = "call",
) -> dict:
    """Compute Black-Scholes Greeks. Returns dict with delta, gamma, theta, vega, price."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "bs_price": 0}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    npd1 = _norm_pdf(d1)

    if option_type == "call":
        delta = nd1
        price = S * nd1 - K * math.exp(-r * T) * nd2
        theta = (
            -S * npd1 * sigma / (2 * sqrt_T)
            - r * K * math.exp(-r * T) * nd2
        ) / 365.0  # daily theta
    else:  # put
        delta = nd1 - 1.0
        nd2_neg = _norm_cdf(-d2)
        nd1_neg = _norm_cdf(-d1)
        price = K * math.exp(-r * T) * nd2_neg - S * nd1_neg
        theta = (
            -S * npd1 * sigma / (2 * sqrt_T)
            + r * K * math.exp(-r * T) * nd2_neg
        ) / 365.0

    gamma = npd1 / (S * sigma * sqrt_T) if (S * sigma * sqrt_T) > 0 else 0
    vega = S * npd1 * sqrt_T / 100.0  # per 1% move in IV

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "bs_price": round(price, 4),
    }


class GreeksCalculator:
    """Compute and persist Greeks for option contracts."""

    async def compute_for_contracts(
        self, contracts: list, underlying_price: float
    ) -> list:
        """Compute Greeks for a list of OptionContract objects and update in DB."""
        if not contracts:
            return contracts

        db: Session = SessionLocal()
        updated = []
        try:
            for contract in contracts:
                # Get fresh reference
                c = db.query(OptionContract).get(contract.id)
                if not c:
                    continue

                sigma = c.iv if c.iv and c.iv > 0 else 0.3  # fallback IV
                T = c.dte / 365.0 if c.dte and c.dte > 0 else 0.01

                greeks = compute_bs_greeks(
                    S=underlying_price,
                    K=c.strike,
                    T=T,
                    sigma=sigma,
                    option_type=c.option_type or "call",
                )

                c.delta = greeks["delta"]
                c.gamma = greeks["gamma"]
                c.theta = greeks["theta"]
                c.vega = greeks["vega"]
                updated.append(c)

            db.commit()

            if updated:
                ticker = updated[0].ticker
                await event_bus.emit(
                    "GREEKS_COMPUTED", "greeks",
                    ticker=ticker,
                    payload={
                        "ticker": ticker,
                        "contracts_computed": len(updated),
                    },
                )
        finally:
            db.close()

        return updated
