"""Centralized configuration loaded from environment / .env file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

# Walk up to repo root to find .env
_here = Path(__file__).resolve().parent
_root = _here.parent.parent  # repo root
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.example")  # fallback defaults


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _float(key: str, default: float = 0.0) -> float:
    return float(_get(key, str(default)))


def _int(key: str, default: int = 0) -> int:
    return int(_get(key, str(default)))


# ── Timezone ─────────────────────────────────────────────────────────
TIMEZONE: str = _get("TIMEZONE", "America/New_York")

# ── RSS Feeds ────────────────────────────────────────────────────────
RSS_FEEDS: List[str] = [
    f.strip() for f in _get("RSS_FEEDS", "").split(",") if f.strip()
]

# ── Watchlist ────────────────────────────────────────────────────────
_raw_wl = _get("WATCHLIST_JSON", "{}")
WATCHLIST: Dict[str, List[str]] = json.loads(_raw_wl) if _raw_wl else {}

# ── Polling ──────────────────────────────────────────────────────────
NEWS_POLL_SECONDS: int = _int("NEWS_POLL_SECONDS", 180)
OPTIONS_REFRESH_MINUTES: int = _int("OPTIONS_REFRESH_MINUTES", 30)
DECISION_TICK_MINUTES: int = _int("DECISION_TICK_MINUTES", 30)

# ── Market hours (ET strings) ───────────────────────────────────────
MARKET_OPEN_ET: str = _get("MARKET_OPEN_ET", "09:30")
MARKET_CLOSE_ET: str = _get("MARKET_CLOSE_ET", "16:00")
LAST_ENTRY_TIME_ET: str = _get("LAST_ENTRY_TIME_ET", "15:00")

# ── Candidate thresholds ────────────────────────────────────────────
MIN_SENTIMENT_MAG: float = _float("MIN_SENTIMENT_MAG", 0.65)
MIN_CONFIDENCE: float = _float("MIN_CONFIDENCE", 0.75)
MIN_COVERAGE_SCORE: int = _int("MIN_COVERAGE_SCORE", 3)
MIN_DISTINCT_SOURCES: int = _int("MIN_DISTINCT_SOURCES", 2)
MAX_CANDIDATES_PER_CYCLE: int = _int("MAX_CANDIDATES_PER_CYCLE", 5)
CANDIDATE_COOLDOWN_MINUTES: int = _int("CANDIDATE_COOLDOWN_MINUTES", 60)

# ── Trade limits ─────────────────────────────────────────────────────
MAX_NEW_TRADES_PER_TICK: int = _int("MAX_NEW_TRADES_PER_TICK", 3)
MAX_OPEN_POSITIONS: int = _int("MAX_OPEN_POSITIONS", 6)
PER_TICKER_MAX_POSITIONS: int = _int("PER_TICKER_MAX_POSITIONS", 1)

# ── Options selection ────────────────────────────────────────────────
DELTA_TARGET_MIN: float = _float("DELTA_TARGET_MIN", 0.45)
DELTA_TARGET_MAX: float = _float("DELTA_TARGET_MAX", 0.65)
STRIKE_WINDOW: int = _int("STRIKE_WINDOW", 10)
EXPIRY_NEAR_DTE_MIN: int = _int("EXPIRY_NEAR_DTE_MIN", 7)
EXPIRY_NEAR_DTE_MAX: int = _int("EXPIRY_NEAR_DTE_MAX", 14)
EXPIRY_MID_DTE_MIN: int = _int("EXPIRY_MID_DTE_MIN", 30)
EXPIRY_MID_DTE_MAX: int = _int("EXPIRY_MID_DTE_MAX", 45)

# ── Risk / Paper Trading ────────────────────────────────────────────
PROFIT_TARGET_PCT: float = _float("PROFIT_TARGET_PCT", 0.30)
STOP_LOSS_PCT: float = _float("STOP_LOSS_PCT", 0.25)
TIME_STOP_HOURS: int = _int("TIME_STOP_HOURS", 6)
STARTING_CASH: float = _float("STARTING_CASH", 100_000)
RISK_PER_TRADE_PCT: float = _float("RISK_PER_TRADE_PCT", 0.01)
SLIPPAGE_PCT: float = _float("SLIPPAGE_PCT", 0.005)

# ── Social Sources ───────────────────────────────────────────────────
REDDIT_SUBREDDITS: List[str] = [
    s.strip() for s in _get(
        "REDDIT_SUBREDDITS", "wallstreetbets,stocks,options,investing"
    ).split(",") if s.strip()
]
REDDIT_POLL_SECONDS: int = _int("REDDIT_POLL_SECONDS", 45)
STOCKTWITS_POLL_SECONDS: int = _int("STOCKTWITS_POLL_SECONDS", 60)
SOCIAL_ENABLED: bool = _get("SOCIAL_ENABLED", "true").lower() == "true"

# ── Source Tier Mapping ──────────────────────────────────────────────
TIER_1_KEYWORDS: List[str] = [
    "reuters", "sec.gov", "yahoo finance", "bloomberg", "cnbc",
    "wall street journal", "wsj", "financial times", "barron",
    "associated press", "ap news",
]
REQUIRE_CROSS_TIER: bool = _get("REQUIRE_CROSS_TIER", "false").lower() == "true"

# ── Flow Detection ───────────────────────────────────────────────────
FLOW_VOLUME_SPIKE_MULTIPLIER: float = _float("FLOW_VOLUME_SPIKE_MULTIPLIER", 3.0)
FLOW_OI_SPIKE_MULTIPLIER: float = _float("FLOW_OI_SPIKE_MULTIPLIER", 2.0)

# ── Trigger-based fetch ─────────────────────────────────────────────
TRIGGER_FETCH_COOLDOWN_SECONDS: int = _int("TRIGGER_FETCH_COOLDOWN_SECONDS", 300)

# ── Application Mode ──────────────────────────────────────────────────
# "signal" = alert-only dashboard (no trades), "trade" = paper trading
APP_MODE: str = _get("APP_MODE", "signal")

# ── Database ─────────────────────────────────────────────────────────
DATABASE_URL: str = _get("DATABASE_URL", "sqlite:///./sentiment_options_lab.db")

# ── Server ───────────────────────────────────────────────────────────
BACKEND_HOST: str = _get("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT: int = _int("BACKEND_PORT", 8000)
