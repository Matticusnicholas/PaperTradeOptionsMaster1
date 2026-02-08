"""Global EventBus – persists events to DB and broadcasts via WebSocket."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.tables import Event

logger = logging.getLogger("eventbus")


class EventBus:
    """Singleton-style event bus.  Stores events in DB and pushes to WS clients."""

    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._db_session_factory = None

    def set_db_factory(self, factory) -> None:
        self._db_session_factory = factory

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def emit(
        self,
        event_type: str,
        module: str,
        *,
        ticker: Optional[str] = None,
        severity: str = "info",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        record = {
            "ts": now.isoformat(),
            "event_type": event_type,
            "ticker": ticker,
            "module": module,
            "severity": severity,
            "payload": payload or {},
        }

        # Persist to DB
        if self._db_session_factory:
            try:
                db: Session = self._db_session_factory()
                evt = Event(
                    ts=now,
                    event_type=event_type,
                    ticker=ticker,
                    module=module,
                    severity=severity,
                    payload=payload or {},
                )
                db.add(evt)
                db.commit()
                record["id"] = evt.id
                db.close()
            except Exception as exc:
                logger.error("Failed to persist event: %s", exc)

        # Broadcast to WS subscribers
        msg = json.dumps(record, default=str)
        dead: List[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

        logger.debug("[%s] %s ticker=%s", event_type, module, ticker)


# Module-level singleton
event_bus = EventBus()
