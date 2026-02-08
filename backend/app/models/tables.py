"""All SQLAlchemy ORM table definitions."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Column, Integer, Float, String, Text, DateTime, Boolean, ForeignKey, JSON, Index,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class NewsItem(Base):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guid = Column(String(512), unique=True, nullable=False, index=True)
    ts = Column(DateTime, default=_utcnow, index=True)
    source = Column(String(256))
    url = Column(Text)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    text = Column(Text)
    raw_hash = Column(String(64))

    mentions = relationship("TickerMention", back_populates="news_item", cascade="all, delete-orphan")
    sentiments = relationship("SentimentScore", back_populates="news_item", cascade="all, delete-orphan")


class TickerMention(Base):
    __tablename__ = "ticker_mentions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    news_id = Column(Integer, ForeignKey("news_items.id"), nullable=False, index=True)
    ticker = Column(String(16), nullable=False, index=True)
    relevance = Column(Float, default=0.5)
    matched_aliases = Column(JSON)

    news_item = relationship("NewsItem", back_populates="mentions")


class SentimentScore(Base):
    __tablename__ = "sentiment_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    news_id = Column(Integer, ForeignKey("news_items.id"), nullable=False, index=True)
    ticker = Column(String(16), nullable=False, index=True)
    label = Column(String(16))  # bullish / bearish / neutral
    score = Column(Float)  # -1 to +1
    confidence = Column(Float)  # 0 to 1
    intensity = Column(Float)
    narrative_tags = Column(JSON)
    key_phrases = Column(JSON)
    explanation = Column(Text)
    created_at = Column(DateTime, default=_utcnow)

    news_item = relationship("NewsItem", back_populates="sentiments")

    __table_args__ = (
        Index("ix_sentiment_ticker_ts", "ticker", "created_at"),
    )


class CoverageMetric(Base):
    __tablename__ = "coverage_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    window_start = Column(DateTime)
    window_end = Column(DateTime)
    coverage_score = Column(Float)
    distinct_sources = Column(Integer)
    cluster_count = Column(Integer)
    mention_count = Column(Integer)
    created_at = Column(DateTime, default=_utcnow)


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    direction = Column(String(16))  # bullish / bearish
    urgency = Column(Float)
    sentiment_score = Column(Float)
    confidence = Column(Float)
    coverage_score = Column(Float)
    distinct_sources = Column(Integer)
    rationale = Column(Text)
    narrative_tags = Column(JSON)
    status = Column(String(16), default="active")  # active / dropped / traded
    cooldown_until = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class OptionChainSnapshot(Base):
    __tablename__ = "option_chain_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    fetched_at = Column(DateTime, default=_utcnow)
    expiry = Column(String(16))
    underlying_price = Column(Float)
    raw_json = Column(JSON)


class OptionContract(Base):
    __tablename__ = "option_contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("option_chain_snapshots.id"), nullable=False, index=True)
    ticker = Column(String(16), nullable=False, index=True)
    contract_symbol = Column(String(64))
    option_type = Column(String(4))  # call / put
    strike = Column(Float)
    expiry = Column(String(16))
    bid = Column(Float)
    ask = Column(Float)
    last_price = Column(Float)
    volume = Column(Integer)
    open_interest = Column(Integer)
    iv = Column(Float)
    delta = Column(Float)
    gamma = Column(Float)
    theta = Column(Float)
    vega = Column(Float)
    dte = Column(Integer)
    moneyness = Column(Float)
    score = Column(Float)
    score_breakdown = Column(JSON)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    contract_id = Column(Integer, ForeignKey("option_contracts.id"))
    contract_symbol = Column(String(64))
    option_type = Column(String(4))
    strike = Column(Float)
    expiry = Column(String(16))
    direction = Column(String(4))  # buy / sell
    quantity = Column(Integer)
    limit_price = Column(Float)
    status = Column(String(16), default="pending")  # pending / filled / cancelled
    profit_target = Column(Float)
    stop_loss = Column(Float)
    time_stop_at = Column(DateTime)
    rationale = Column(Text)
    created_at = Column(DateTime, default=_utcnow)


class Fill(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    fill_price = Column(Float)
    quantity = Column(Integer)
    slippage = Column(Float)
    filled_at = Column(DateTime, default=_utcnow)


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    contract_symbol = Column(String(64))
    option_type = Column(String(4))
    strike = Column(Float)
    expiry = Column(String(16))
    quantity = Column(Integer)
    entry_price = Column(Float)
    current_price = Column(Float)
    unrealized_pnl = Column(Float)
    realized_pnl = Column(Float, default=0.0)
    profit_target = Column(Float)
    stop_loss = Column(Float)
    time_stop_at = Column(DateTime)
    status = Column(String(16), default="open")  # open / closed
    exit_reason = Column(String(32))
    opened_at = Column(DateTime, default=_utcnow)
    closed_at = Column(DateTime)
    order_id = Column(Integer, ForeignKey("orders.id"))
    candidate_id = Column(Integer, ForeignKey("candidates.id"))

    __table_args__ = (
        Index("ix_position_status", "status"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=_utcnow, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    ticker = Column(String(16), index=True)
    module = Column(String(64))
    severity = Column(String(16), default="info")  # info / warning / error
    payload = Column(JSON)

    __table_args__ = (
        Index("ix_event_type_ts", "event_type", "ts"),
    )


class AccountState(Base):
    __tablename__ = "account_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cash = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    open_positions_count = Column(Integer, default=0)
    total_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=_utcnow)
