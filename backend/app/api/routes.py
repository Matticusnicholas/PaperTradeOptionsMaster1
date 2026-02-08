"""FastAPI REST + WebSocket endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import (
    AccountState, Candidate, CoverageMetric, Event, Fill, NewsItem,
    OptionContract, Order, Position, SentimentScore, TickerMention,
)
from app.modules.event_bus import event_bus
from app.modules.market_clock import MarketClock

logger = logging.getLogger("api")

router = APIRouter()

# ── WebSocket for live events ───────────────────────────────────────

@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    queue = event_bus.subscribe()
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WS error: %s", e)
    finally:
        event_bus.unsubscribe(queue)


# ── App Mode ─────────────────────────────────────────────────────────

@router.get("/api/mode")
def get_app_mode():
    from app.config import APP_MODE
    return {"mode": APP_MODE}


# ── News ─────────────────────────────────────────────────────────────

@router.get("/api/news")
def get_news(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = None,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(NewsItem).order_by(desc(NewsItem.ts))
    if ticker:
        news_ids = [
            m.news_id for m in
            db.query(TickerMention.news_id).filter(TickerMention.ticker == ticker).all()
        ]
        q = q.filter(NewsItem.id.in_(news_ids))
    if source_type:
        q = q.filter(NewsItem.source_type == source_type)
    items = q.offset(offset).limit(limit).all()
    return [
        {
            "id": n.id, "ts": n.ts.isoformat() if n.ts else None,
            "source": n.source, "url": n.url,
            "title": n.title, "summary": (n.summary or "")[:300],
            "source_type": n.source_type or "rss",
            "source_tier": n.source_tier or 2,
        }
        for n in items
    ]


@router.get("/api/news/{news_id}")
def get_news_detail(news_id: int, db: Session = Depends(get_db)):
    n = db.query(NewsItem).get(news_id)
    if not n:
        return {"error": "not found"}
    mentions = db.query(TickerMention).filter_by(news_id=news_id).all()
    sentiments = db.query(SentimentScore).filter_by(news_id=news_id).all()
    return {
        "id": n.id, "ts": n.ts.isoformat() if n.ts else None,
        "source": n.source, "url": n.url,
        "title": n.title, "summary": n.summary, "text": n.text,
        "source_type": n.source_type or "rss",
        "source_tier": n.source_tier or 2,
        "tickers": [
            {"ticker": m.ticker, "relevance": m.relevance, "aliases": m.matched_aliases}
            for m in mentions
        ],
        "sentiments": [
            {
                "ticker": s.ticker, "label": s.label, "score": s.score,
                "confidence": s.confidence, "intensity": s.intensity,
                "tags": s.narrative_tags, "key_phrases": s.key_phrases,
                "explanation": s.explanation,
            }
            for s in sentiments
        ],
    }


# ── Sentiment ────────────────────────────────────────────────────────

@router.get("/api/sentiment")
def get_sentiment(
    ticker: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(SentimentScore).order_by(desc(SentimentScore.created_at))
    if ticker:
        q = q.filter(SentimentScore.ticker == ticker)
    items = q.limit(limit).all()
    return [
        {
            "id": s.id, "news_id": s.news_id, "ticker": s.ticker,
            "label": s.label, "score": s.score, "confidence": s.confidence,
            "intensity": s.intensity, "tags": s.narrative_tags,
            "key_phrases": s.key_phrases, "explanation": s.explanation,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in items
    ]


# ── Coverage ─────────────────────────────────────────────────────────

@router.get("/api/coverage")
def get_coverage(
    ticker: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(CoverageMetric).order_by(desc(CoverageMetric.id))
    if ticker:
        q = q.filter(CoverageMetric.ticker == ticker)
    items = q.limit(limit).all()
    return [
        {
            "id": c.id, "ticker": c.ticker,
            "coverage_score": c.coverage_score,
            "distinct_sources": c.distinct_sources,
            "tier_1_sources": c.tier_1_sources or 0,
            "tier_2_sources": c.tier_2_sources or 0,
            "cross_tier_confirmed": c.cross_tier_confirmed or False,
            "cluster_count": c.cluster_count,
            "mention_count": c.mention_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in items
    ]


# ── Candidates ───────────────────────────────────────────────────────

@router.get("/api/candidates")
def get_candidates(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Candidate).order_by(desc(Candidate.urgency))
    if status:
        q = q.filter(Candidate.status == status)
    items = q.limit(limit).all()
    return [
        {
            "id": c.id, "ticker": c.ticker, "direction": c.direction,
            "urgency": c.urgency, "sentiment_score": c.sentiment_score,
            "confidence": c.confidence, "coverage_score": c.coverage_score,
            "distinct_sources": c.distinct_sources, "rationale": c.rationale,
            "narrative_tags": c.narrative_tags, "status": c.status,
            "cross_tier_confirmed": c.cross_tier_confirmed or False,
            "flow_confirmed": c.flow_confirmed or False,
            "flow_score": c.flow_score or 0.0,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in items
    ]


# ── Signal Alerts (signal mode) ────────────────────────────────────

@router.get("/api/signals")
def get_signals(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Returns SIGNAL_ALERT and WATCH_ALERT events for the signal hub."""
    items = (
        db.query(Event)
        .filter(Event.event_type.in_(["SIGNAL_ALERT", "WATCH_ALERT"]))
        .order_by(desc(Event.ts))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id, "ts": e.ts.isoformat() if e.ts else None,
            "event_type": e.event_type, "ticker": e.ticker,
            "severity": e.severity, "payload": e.payload,
        }
        for e in items
    ]


# ── Options Contracts ────────────────────────────────────────────────

@router.get("/api/options/contracts")
def get_option_contracts(
    ticker: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(OptionContract).order_by(desc(OptionContract.id))
    if ticker:
        q = q.filter(OptionContract.ticker == ticker)
    items = q.limit(limit).all()
    return [
        {
            "id": c.id, "ticker": c.ticker,
            "contract_symbol": c.contract_symbol,
            "option_type": c.option_type, "strike": c.strike,
            "expiry": c.expiry, "bid": c.bid, "ask": c.ask,
            "last_price": c.last_price, "volume": c.volume,
            "open_interest": c.open_interest, "iv": c.iv,
            "delta": c.delta, "gamma": c.gamma, "theta": c.theta, "vega": c.vega,
            "dte": c.dte, "moneyness": c.moneyness,
            "score": c.score, "score_breakdown": c.score_breakdown,
        }
        for c in items
    ]


# ── Orders ───────────────────────────────────────────────────────────

@router.get("/api/orders")
def get_orders(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Order).order_by(desc(Order.created_at))
    if status:
        q = q.filter(Order.status == status)
    items = q.limit(limit).all()
    return [
        {
            "id": o.id, "ticker": o.ticker,
            "contract_symbol": o.contract_symbol,
            "option_type": o.option_type, "strike": o.strike,
            "expiry": o.expiry, "direction": o.direction,
            "quantity": o.quantity, "limit_price": o.limit_price,
            "status": o.status,
            "profit_target": o.profit_target, "stop_loss": o.stop_loss,
            "rationale": o.rationale,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in items
    ]


# ── Positions ────────────────────────────────────────────────────────

@router.get("/api/positions")
def get_positions(
    status: Optional[str] = Query("open"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Position).order_by(desc(Position.opened_at))
    if status:
        q = q.filter(Position.status == status)
    items = q.limit(limit).all()
    return [
        {
            "id": p.id, "ticker": p.ticker,
            "contract_symbol": p.contract_symbol,
            "option_type": p.option_type, "strike": p.strike,
            "expiry": p.expiry, "quantity": p.quantity,
            "entry_price": p.entry_price, "current_price": p.current_price,
            "unrealized_pnl": p.unrealized_pnl, "realized_pnl": p.realized_pnl,
            "profit_target": p.profit_target, "stop_loss": p.stop_loss,
            "status": p.status, "exit_reason": p.exit_reason,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        }
        for p in items
    ]


# ── Trades (closed) ─────────────────────────────────────────────────

@router.get("/api/trades")
def get_trades(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items = (
        db.query(Position)
        .filter(Position.status == "closed")
        .order_by(desc(Position.closed_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id, "ticker": p.ticker,
            "contract_symbol": p.contract_symbol,
            "option_type": p.option_type, "strike": p.strike,
            "expiry": p.expiry, "quantity": p.quantity,
            "entry_price": p.entry_price, "current_price": p.current_price,
            "realized_pnl": p.realized_pnl,
            "exit_reason": p.exit_reason,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        }
        for p in items
    ]


# ── Account ──────────────────────────────────────────────────────────

@router.get("/api/account")
def get_account(db: Session = Depends(get_db)):
    acct = db.query(AccountState).order_by(desc(AccountState.id)).first()
    if not acct:
        return {"cash": 0, "equity": 0, "open_positions": 0, "total_trades": 0, "total_pnl": 0}
    return {
        "cash": acct.cash, "equity": acct.equity,
        "open_positions": acct.open_positions_count,
        "total_trades": acct.total_trades,
        "total_pnl": acct.total_pnl,
        "updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
    }


# ── Events ───────────────────────────────────────────────────────────

@router.get("/api/events")
def get_events(
    event_type: Optional[str] = None,
    ticker: Optional[str] = None,
    severity: Optional[str] = None,
    module: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(Event).order_by(desc(Event.ts))
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if ticker:
        q = q.filter(Event.ticker == ticker)
    if severity:
        q = q.filter(Event.severity == severity)
    if module:
        q = q.filter(Event.module == module)
    items = q.limit(limit).all()
    return [
        {
            "id": e.id, "ts": e.ts.isoformat() if e.ts else None,
            "event_type": e.event_type, "ticker": e.ticker,
            "module": e.module, "severity": e.severity,
            "payload": e.payload,
        }
        for e in items
    ]


# ── Market Clock ─────────────────────────────────────────────────────

@router.get("/api/market-clock")
def get_market_clock():
    clock = MarketClock()
    ms = clock.status()
    return {
        "status": ms.status_text,
        "is_market_open": ms.is_market_open,
        "can_enter_new": ms.can_enter_new,
        "is_after_cutoff": ms.is_after_cutoff,
        "current_et": ms.current_et.isoformat(),
    }


# ── System Health ────────────────────────────────────────────────────

@router.get("/api/health")
def get_health(db: Session = Depends(get_db)):
    from app.config import APP_MODE, SOCIAL_ENABLED
    news_count = db.query(NewsItem).count()
    last_news = db.query(NewsItem).order_by(desc(NewsItem.ts)).first()
    last_event = db.query(Event).order_by(desc(Event.ts)).first()
    candidates_active = db.query(Candidate).filter(Candidate.status == "active").count()
    open_positions = db.query(Position).filter(Position.status == "open").count()
    signal_count = (
        db.query(Event)
        .filter(Event.event_type.in_(["SIGNAL_ALERT", "WATCH_ALERT"]))
        .count()
    )

    return {
        "status": "running",
        "mode": APP_MODE,
        "social_enabled": SOCIAL_ENABLED,
        "news_count": news_count,
        "signal_count": signal_count,
        "last_news_at": last_news.ts.isoformat() if last_news and last_news.ts else None,
        "last_event_at": last_event.ts.isoformat() if last_event and last_event.ts else None,
        "active_candidates": candidates_active,
        "open_positions": open_positions,
    }


# ── Ticker overview ──────────────────────────────────────────────────

@router.get("/api/ticker/{ticker}")
def get_ticker_view(ticker: str, db: Session = Depends(get_db)):
    sentiments = (
        db.query(SentimentScore)
        .filter(SentimentScore.ticker == ticker)
        .order_by(desc(SentimentScore.created_at))
        .limit(50)
        .all()
    )
    coverage = (
        db.query(CoverageMetric)
        .filter(CoverageMetric.ticker == ticker)
        .order_by(desc(CoverageMetric.id))
        .limit(20)
        .all()
    )
    candidate = (
        db.query(Candidate)
        .filter(Candidate.ticker == ticker, Candidate.status == "active")
        .first()
    )
    positions = (
        db.query(Position)
        .filter(Position.ticker == ticker)
        .order_by(desc(Position.opened_at))
        .limit(10)
        .all()
    )
    signals = (
        db.query(Event)
        .filter(
            Event.ticker == ticker,
            Event.event_type.in_(["SIGNAL_ALERT", "WATCH_ALERT"]),
        )
        .order_by(desc(Event.ts))
        .limit(10)
        .all()
    )

    return {
        "ticker": ticker,
        "sentiments": [
            {"score": s.score, "label": s.label, "confidence": s.confidence,
             "tags": s.narrative_tags, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in sentiments
        ],
        "coverage": [
            {"coverage_score": c.coverage_score, "distinct_sources": c.distinct_sources,
             "tier_1_sources": c.tier_1_sources or 0, "tier_2_sources": c.tier_2_sources or 0,
             "cross_tier_confirmed": c.cross_tier_confirmed or False,
             "mention_count": c.mention_count, "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in coverage
        ],
        "candidate": {
            "direction": candidate.direction, "urgency": candidate.urgency,
            "rationale": candidate.rationale,
            "cross_tier_confirmed": candidate.cross_tier_confirmed or False,
            "flow_confirmed": candidate.flow_confirmed or False,
            "flow_score": candidate.flow_score or 0.0,
        } if candidate else None,
        "signals": [
            {"event_type": e.event_type, "ts": e.ts.isoformat() if e.ts else None,
             "severity": e.severity, "payload": e.payload}
            for e in signals
        ],
        "positions": [
            {"id": p.id, "status": p.status, "entry_price": p.entry_price,
             "current_price": p.current_price, "unrealized_pnl": p.unrealized_pnl,
             "realized_pnl": p.realized_pnl, "exit_reason": p.exit_reason}
            for p in positions
        ],
    }
