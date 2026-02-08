"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import APP_MODE, BACKEND_HOST, BACKEND_PORT
from app.database import SessionLocal
from app.init_db import init_db
from app.modules.event_bus import event_bus
from app.modules.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-20s] %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

app = FastAPI(
    title="Sentiment Options Lab",
    description="Real-time sentiment-driven options signal dashboard",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

orchestrator = Orchestrator(mode=APP_MODE)


@app.on_event("startup")
async def on_startup():
    logger.info("Initializing database...")
    init_db()

    # Wire event bus to DB
    event_bus.set_db_factory(SessionLocal)

    # Ensure account state only in trade mode
    if orchestrator.sim_broker:
        orchestrator.sim_broker._ensure_account()

    logger.info("Starting orchestrator in %s mode...", APP_MODE.upper())
    asyncio.create_task(orchestrator.start())

    await event_bus.emit(
        "MARKET_CLOCK_STATUS", "main",
        payload={"message": f"Application started ({APP_MODE} mode)", "mode": APP_MODE},
    )


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down orchestrator...")
    await orchestrator.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=BACKEND_HOST, port=BACKEND_PORT, reload=True)
