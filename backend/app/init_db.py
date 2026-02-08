"""Create all tables (for quick dev start without Alembic)."""

from app.models.base import Base
from app.models.tables import (  # noqa: F401 – import to register models
    NewsItem, TickerMention, SentimentScore, CoverageMetric,
    Candidate, OptionChainSnapshot, OptionContract,
    Order, Fill, Position, Event, AccountState,
)
from app.database import engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Database tables created.")
