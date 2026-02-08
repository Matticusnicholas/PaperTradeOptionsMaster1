"""CoverageIntensityTracker – tracks how widely a ticker/story is mentioned."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.tables import (
    CoverageMetric, NewsItem, SentimentScore, TickerMention,
)
from app.modules.event_bus import event_bus

logger = logging.getLogger("coverage_tracker")


class CoverageIntensityTracker:
    """Compute per-ticker coverage_score over rolling windows."""

    def __init__(self, window_minutes: int = 60) -> None:
        self.window_minutes = window_minutes

    async def update(self, ticker: str) -> Optional[CoverageMetric]:
        """Recalculate coverage for a ticker over the rolling window."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=self.window_minutes)

        db: Session = SessionLocal()
        try:
            # Get all mentions in window
            mentions = (
                db.query(TickerMention, NewsItem)
                .join(NewsItem, TickerMention.news_id == NewsItem.id)
                .filter(
                    TickerMention.ticker == ticker,
                    NewsItem.ts >= window_start,
                )
                .all()
            )

            if not mentions:
                return None

            mention_count = len(mentions)
            sources = set()
            titles: List[str] = []

            for mention, news in mentions:
                sources.add(news.source or "unknown")
                titles.append(news.title or "")

            distinct_sources = len(sources)

            # Cluster detection: group similar titles
            clusters = self._cluster_titles(titles)
            cluster_count = len(clusters)

            # Coverage score formula:
            # mention_count + source_diversity_bonus + independent_cluster_bonus
            source_bonus = distinct_sources * 1.5
            cluster_bonus = max(0, cluster_count - 1) * 2.0  # >1 cluster = independent reports
            coverage_score = mention_count + source_bonus + cluster_bonus

            metric = CoverageMetric(
                ticker=ticker,
                window_start=window_start,
                window_end=now,
                coverage_score=round(coverage_score, 2),
                distinct_sources=distinct_sources,
                cluster_count=cluster_count,
                mention_count=mention_count,
            )
            db.add(metric)
            db.commit()
            db.refresh(metric)

            await event_bus.emit(
                "COVERAGE_UPDATED", "coverage_tracker",
                ticker=ticker,
                payload={
                    "ticker": ticker,
                    "coverage_score": metric.coverage_score,
                    "distinct_sources": distinct_sources,
                    "cluster_count": cluster_count,
                    "mention_count": mention_count,
                    "window_minutes": self.window_minutes,
                },
            )

            return metric
        finally:
            db.close()

    def _cluster_titles(self, titles: List[str], threshold: float = 0.65) -> List[List[str]]:
        """Group similar titles into clusters."""
        if not titles:
            return []
        clusters: List[List[str]] = []
        assigned = [False] * len(titles)

        for i, t1 in enumerate(titles):
            if assigned[i]:
                continue
            cluster = [t1]
            assigned[i] = True
            for j in range(i + 1, len(titles)):
                if assigned[j]:
                    continue
                if SequenceMatcher(None, t1.lower(), titles[j].lower()).ratio() >= threshold:
                    cluster.append(titles[j])
                    assigned[j] = True
            clusters.append(cluster)
        return clusters

    async def get_latest(self, ticker: str) -> Optional[CoverageMetric]:
        db: Session = SessionLocal()
        try:
            return (
                db.query(CoverageMetric)
                .filter_by(ticker=ticker)
                .order_by(CoverageMetric.id.desc())
                .first()
            )
        finally:
            db.close()
