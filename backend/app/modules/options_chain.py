"""OptionsChainProvider – fetch options chain data via yfinance for candidates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import yfinance as yf

from app.config import (
    EXPIRY_MID_DTE_MAX,
    EXPIRY_MID_DTE_MIN,
    EXPIRY_NEAR_DTE_MAX,
    EXPIRY_NEAR_DTE_MIN,
    OPTIONS_REFRESH_MINUTES,
    STRIKE_WINDOW,
)
from app.database import SessionLocal
from app.models.tables import OptionChainSnapshot, OptionContract
from app.modules.event_bus import event_bus

logger = logging.getLogger("options_chain")

# Track last fetch time per ticker
_last_fetch: Dict[str, float] = {}


class OptionsChainProvider:
    """Fetch options chains for candidate tickers, respecting throttle cadence."""

    def __init__(self) -> None:
        self.refresh_interval = OPTIONS_REFRESH_MINUTES * 60
        self.strike_window = STRIKE_WINDOW
        self.near_dte = (EXPIRY_NEAR_DTE_MIN, EXPIRY_NEAR_DTE_MAX)
        self.mid_dte = (EXPIRY_MID_DTE_MIN, EXPIRY_MID_DTE_MAX)
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def should_fetch(self, ticker: str) -> bool:
        last = _last_fetch.get(ticker, 0)
        return (time.time() - last) >= self.refresh_interval

    async def fetch_chain(
        self, ticker: str, underlying_price: float
    ) -> List[OptionContract]:
        """Fetch options chain for a ticker. Returns list of OptionContract rows."""
        if not self.should_fetch(ticker):
            logger.debug("Skipping %s (throttled)", ticker)
            return []

        try:
            loop = asyncio.get_event_loop()
            contracts = await loop.run_in_executor(
                None, self._fetch_sync, ticker, underlying_price
            )
            _last_fetch[ticker] = time.time()

            await event_bus.emit(
                "OPTIONS_CHAIN_FETCHED", "options_chain",
                ticker=ticker,
                payload={
                    "ticker": ticker,
                    "contracts_count": len(contracts),
                    "underlying_price": underlying_price,
                },
            )
            return contracts

        except Exception as exc:
            logger.error("Options fetch failed for %s: %s", ticker, exc)
            await event_bus.emit(
                "ERROR", "options_chain",
                ticker=ticker,
                severity="warning",
                payload={"error": str(exc), "ticker": ticker},
            )
            return []

    def _fetch_sync(self, ticker: str, underlying_price: float) -> List[OptionContract]:
        self._call_count += 1
        t = yf.Ticker(ticker)

        try:
            expirations = t.options  # list of date strings
        except Exception:
            logger.warning("No options available for %s", ticker)
            return []

        if not expirations:
            return []

        # Select expirations in our DTE windows
        today = datetime.now().date()
        selected_expiries = self._select_expirations(expirations, today)

        if not selected_expiries:
            logger.info("No suitable expirations for %s", ticker)
            return []

        all_contracts: List[OptionContract] = []
        db = SessionLocal()

        try:
            for exp_str in selected_expiries:
                try:
                    chain = t.option_chain(exp_str)
                except Exception as e:
                    logger.warning("Failed to get chain for %s %s: %s", ticker, exp_str, e)
                    continue

                # Store snapshot
                snapshot = OptionChainSnapshot(
                    ticker=ticker,
                    expiry=exp_str,
                    underlying_price=underlying_price,
                    raw_json={"expiry": exp_str, "calls_count": len(chain.calls), "puts_count": len(chain.puts)},
                )
                db.add(snapshot)
                db.flush()

                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days

                # Process calls and puts
                for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                    contracts = self._process_chain_df(
                        db, df, snapshot.id, ticker, exp_str, opt_type,
                        underlying_price, dte,
                    )
                    all_contracts.extend(contracts)

            db.commit()
            for c in all_contracts:
                db.refresh(c)
        finally:
            db.close()

        return all_contracts

    def _select_expirations(
        self, expirations: list, today
    ) -> List[str]:
        """Pick near-term + mid-term expirations."""
        selected = []
        near_found = 0
        mid_found = False

        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            dte = (exp_date - today).days
            if dte < 1:
                continue

            if self.near_dte[0] <= dte <= self.near_dte[1] and near_found < 2:
                selected.append(exp_str)
                near_found += 1
            elif self.mid_dte[0] <= dte <= self.mid_dte[1] and not mid_found:
                selected.append(exp_str)
                mid_found = True

            if near_found >= 2 and mid_found:
                break

        # Fallback: if no near-term, take first available
        if not selected and expirations:
            for exp_str in expirations[:2]:
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    dte = (exp_date - today).days
                    if dte >= 1:
                        selected.append(exp_str)
                except ValueError:
                    continue

        return selected

    def _process_chain_df(
        self, db, df, snapshot_id: int, ticker: str, expiry: str,
        opt_type: str, underlying_price: float, dte: int,
    ) -> List[OptionContract]:
        """Filter strikes around ATM and create OptionContract rows."""
        if df is None or df.empty:
            return []

        contracts = []
        # Filter to ±STRIKE_WINDOW strikes around ATM
        strikes = df["strike"].values
        atm_idx = abs(strikes - underlying_price).argmin()
        low = max(0, atm_idx - self.strike_window)
        high = min(len(strikes), atm_idx + self.strike_window + 1)
        filtered = df.iloc[low:high]

        for _, row in filtered.iterrows():
            strike = float(row.get("strike", 0))
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)
            volume = int(row.get("volume", 0) or 0)
            oi = int(row.get("openInterest", 0) or 0)
            iv = float(row.get("impliedVolatility", 0) or 0)
            symbol = str(row.get("contractSymbol", ""))

            moneyness = strike / underlying_price if underlying_price > 0 else 0

            contract = OptionContract(
                snapshot_id=snapshot_id,
                ticker=ticker,
                contract_symbol=symbol,
                option_type=opt_type,
                strike=strike,
                expiry=expiry,
                bid=bid,
                ask=ask,
                last_price=last_price,
                volume=volume,
                open_interest=oi,
                iv=iv,
                dte=dte,
                moneyness=round(moneyness, 4),
            )
            db.add(contract)
            contracts.append(contract)

        return contracts
