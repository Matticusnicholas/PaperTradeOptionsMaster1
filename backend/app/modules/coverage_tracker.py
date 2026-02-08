"""CoverageIntensityTracker – tier-weighted cross-confirmation coverage scoring."""

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

# Tier weights: authoritative sources count more
TIER_WEIGHTS = {
    1: 3.0,  # Reuters, Bloomberg, Yahoo Finance, etc.
    2: 1.0,  # Reddit, StockTwits, generic RSS
    3: 0.5,  # Low-trust blogs, unknown sources
}


class CoverageIntensityTracker:
    """Compute per-ticker coverage_score over rolling windows with tier weighting."""

    def __init__(self, window_minutes: int = 60) -> None:
        self.window_minutes = window_minutes

    async def update(self, ticker: str) -> Optional[CoverageMetric]:
        """Recalculate coverage for a ticker over the rolling window."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=self.window_minutes)

        db: Session = SessionLocal()
        try:
            # Get all mentions in window with full news item data
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
            tier_1_sources = set()
            tier_2_sources = set()

            for mention, news in mentions:
                source_name = news.source or "unknown"
                sources.add(source_name)
                titles.append(news.title or "")

                tier = news.source_tier or 2
                if tier == 1:
                    tier_1_sources.add(source_name)
                else:
                    tier_2_sources.add(source_name)

            distinct_sources = len(sources)

            # Cluster detection
            clusters = self._cluster_titles(titles)
            cluster_count = len(clusters)

            # ── Tier-weighted coverage score ──
            weighted_mentions = 0.0
            for mention, news in mentions:
                tier = news.source_tier or 2
                weighted_mentions += TIER_WEIGHTS.get(tier, 1.0)

            # Source diversity bonus (tier 1 sources worth more)
            t1_bonus = len(tier_1_sources) * 3.0
            t2_bonus = len(tier_2_sources) * 1.0
            source_bonus = t1_bonus + t2_bonus

            # Independent cluster bonus
            cluster_bonus = max(0, cluster_count - 1) * 2.0

            # Cross-tier confirmation bonus (biggest signal)
            cross_confirmed = len(tier_1_sources) > 0 and len(tier_2_sources) > 0
            cross_bonus = 10.0 if cross_confirmed else 0.0

            coverage_score = weighted_mentions + source_bonus + cluster_bonus + cross_bonus

            metric = CoverageMetric(
                ticker=ticker,
                window_start=window_start,
                window_end=now,
                coverage_score=round(coverage_score, 2),
                distinct_sources=distinct_sources,
                tier_1_sources=len(tier_1_sources),
                tier_2_sources=len(tier_2_sources),
                cross_tier_confirmed=cross_confirmed,
                cluster_count=cluster_count,
                mention_count=mention_count,
            )
            db.add(metric)
            db.commit()
            db.refresh(metric)

            if cross_confirmed:
                logger.info(
                    "CROSS-TIER CONFIRMED for %s: %d tier-1 + %d tier-2 sources",
                    ticker, len(tier_1_sources), len(tier_2_sources),
                )

            await event_bus.emit(
                "COVERAGE_UPDATED", "coverage_tracker",
                ticker=ticker,
                payload={
                    "ticker": ticker,
                    "coverage_score": metric.coverage_score,
                    "distinct_sources": distinct_sources,
                    "tier_1_sources": len(tier_1_sources),
                    "tier_2_sources": len(tier_2_sources),
                    "cross_tier_confirmed": cross_confirmed,
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
