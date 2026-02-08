"""CandidateFunnel – Stage 1 output. Ranks tickers for Stage 2 options evaluation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    CANDIDATE_COOLDOWN_MINUTES,
    MAX_CANDIDATES_PER_CYCLE,
    MIN_CONFIDENCE,
    MIN_COVERAGE_SCORE,
    MIN_DISTINCT_SOURCES,
    MIN_SENTIMENT_MAG,
    REQUIRE_CROSS_TIER,
)
from app.database import SessionLocal
from app.models.tables import (
    Candidate, CoverageMetric, SentimentScore, TickerMention,
)
from app.modules.event_bus import event_bus

logger = logging.getLogger("candidate_funnel")


class CandidateFunnel:
    """Produce ranked Candidates from sentiment + coverage data."""

    def __init__(self) -> None:
        self.min_sentiment_mag = MIN_SENTIMENT_MAG
        self.min_confidence = MIN_CONFIDENCE
        self.min_coverage = MIN_COVERAGE_SCORE
        self.min_sources = MIN_DISTINCT_SOURCES
        self.max_candidates = MAX_CANDIDATES_PER_CYCLE
        self.cooldown_minutes = CANDIDATE_COOLDOWN_MINUTES

    async def evaluate(self) -> List[Candidate]:
        """Run the funnel across all tickers with recent sentiment data."""
        now = datetime.now(timezone.utc)
        window = now - timedelta(minutes=90)  # look at recent data

        db: Session = SessionLocal()
        try:
            # Get tickers with recent sentiment scores
            ticker_rows = (
                db.query(SentimentScore.ticker)
                .filter(SentimentScore.created_at >= window)
                .distinct()
                .all()
            )
            tickers = [r[0] for r in ticker_rows]

            scored: List[Dict] = []

            for ticker in tickers:
                result = self._evaluate_ticker(db, ticker, window, now)
                if result:
                    scored.append(result)

            # Sort by urgency descending, cap to max
            scored.sort(key=lambda x: x["urgency"], reverse=True)
            scored = scored[:self.max_candidates]

            candidates: List[Candidate] = []
            for item in scored:
                candidate = self._upsert_candidate(db, item, now)
                candidates.append(candidate)

            db.commit()

            for c in candidates:
                db.refresh(c)
                await event_bus.emit(
                    "CANDIDATE_CREATED", "candidate_funnel",
                    ticker=c.ticker,
                    payload={
                        "candidate_id": c.id,
                        "ticker": c.ticker,
                        "direction": c.direction,
                        "urgency": c.urgency,
                        "sentiment_score": c.sentiment_score,
                        "confidence": c.confidence,
                        "coverage_score": c.coverage_score,
                        "rationale": (c.rationale or "")[:300],
                    },
                )

            return candidates
        finally:
            db.close()

    def _evaluate_ticker(
        self, db: Session, ticker: str, window: datetime, now: datetime
    ) -> Optional[Dict]:
        """Evaluate a single ticker against funnel criteria."""
        # Check cooldown
        existing = (
            db.query(Candidate)
            .filter(
                Candidate.ticker == ticker,
                Candidate.status == "active",
                Candidate.cooldown_until != None,
                Candidate.cooldown_until > now,
            )
            .first()
        )
        if existing:
            return None

        # Aggregate sentiment scores
        scores = (
            db.query(SentimentScore)
            .filter(
                SentimentScore.ticker == ticker,
                SentimentScore.created_at >= window,
            )
            .all()
        )
        if not scores:
            return None

        # Weighted average sentiment
        total_weight = 0.0
        weighted_sum = 0.0
        max_confidence = 0.0
        all_tags: List[str] = []
        top_headlines: List[str] = []

        for s in scores:
            w = (s.confidence or 0.5) * (s.intensity or 0.5)
            weighted_sum += (s.score or 0.0) * w
            total_weight += w
            max_confidence = max(max_confidence, s.confidence or 0.0)
            if s.narrative_tags:
                all_tags.extend(s.narrative_tags)
            # Collect headline from related news
            if s.news_item:
                top_headlines.append((s.news_item.title or "")[:120])

        if total_weight == 0:
            return None

        avg_sentiment = weighted_sum / total_weight
        avg_confidence = sum(s.confidence or 0 for s in scores) / len(scores)

        # Get coverage
        coverage = (
            db.query(CoverageMetric)
            .filter(CoverageMetric.ticker == ticker)
            .order_by(CoverageMetric.id.desc())
            .first()
        )
        coverage_score = coverage.coverage_score if coverage else 0
        distinct_sources = coverage.distinct_sources if coverage else 0
        cross_tier = getattr(coverage, "cross_tier_confirmed", False) if coverage else False
        tier_1_count = getattr(coverage, "tier_1_sources", 0) if coverage else 0
        tier_2_count = getattr(coverage, "tier_2_sources", 0) if coverage else 0

        # ── Gating checks ──
        if abs(avg_sentiment) < self.min_sentiment_mag:
            return None
        if avg_confidence < self.min_confidence:
            return None
        if coverage_score < self.min_coverage and distinct_sources < self.min_sources:
            return None

        # Cross-tier gating (if enabled): require both tier 1 + tier 2
        if REQUIRE_CROSS_TIER and not cross_tier:
            return None

        # Catalyst weight
        catalyst_tags = set(all_tags) - {""}
        catalyst_weight = min(1.0, len(catalyst_tags) * 0.15)

        # Urgency formula (with cross-tier and tier-1 boosts)
        urgency = (
            abs(avg_sentiment) * 30
            + avg_confidence * 20
            + catalyst_weight * 25
            + min(coverage_score, 20) * 1.25
        )

        # Cross-tier confirmation boost: +15 urgency (the remora signal)
        if cross_tier:
            urgency += 15

        # Tier 1 authoritative source boost
        if tier_1_count >= 1:
            urgency += 5 * min(tier_1_count, 3)

        urgency = min(100.0, urgency)

        direction = "bullish" if avg_sentiment > 0 else "bearish"

        # Rationale
        unique_tags = list(dict.fromkeys(all_tags))[:8]
        rationale_parts = [
            f"Direction: {direction} (avg_score={avg_sentiment:+.3f})",
            f"Confidence: {avg_confidence:.2f}",
            f"Coverage: {coverage_score:.1f} ({distinct_sources} sources: {tier_1_count} T1, {tier_2_count} T2)",
        ]
        if cross_tier:
            rationale_parts.append("CROSS-TIER CONFIRMED")
        rationale_parts.append(
            f"Catalysts: {', '.join(unique_tags[:5]) if unique_tags else 'none'}"
        )
        if top_headlines:
            rationale_parts.append(f"Top headline: {top_headlines[0]}")

        return {
            "ticker": ticker,
            "direction": direction,
            "urgency": round(urgency, 2),
            "sentiment_score": round(avg_sentiment, 4),
            "confidence": round(avg_confidence, 4),
            "coverage_score": coverage_score,
            "distinct_sources": distinct_sources,
            "cross_tier_confirmed": cross_tier,
            "narrative_tags": unique_tags,
            "rationale": " | ".join(rationale_parts),
        }

    def _upsert_candidate(self, db: Session, data: Dict, now: datetime) -> Candidate:
        """Create or update a candidate record."""
        existing = (
            db.query(Candidate)
            .filter(
                Candidate.ticker == data["ticker"],
                Candidate.status == "active",
            )
            .first()
        )

        cooldown_until = now + timedelta(minutes=self.cooldown_minutes)

        if existing:
            existing.direction = data["direction"]
            existing.urgency = data["urgency"]
            existing.sentiment_score = data["sentiment_score"]
            existing.confidence = data["confidence"]
            existing.coverage_score = data["coverage_score"]
            existing.distinct_sources = data["distinct_sources"]
            existing.narrative_tags = data["narrative_tags"]
            existing.rationale = data["rationale"]
            existing.cross_tier_confirmed = data.get("cross_tier_confirmed", False)
            existing.updated_at = now
            return existing

        candidate = Candidate(
            ticker=data["ticker"],
            direction=data["direction"],
            urgency=data["urgency"],
            sentiment_score=data["sentiment_score"],
            confidence=data["confidence"],
            coverage_score=data["coverage_score"],
            distinct_sources=data["distinct_sources"],
            narrative_tags=data["narrative_tags"],
            rationale=data["rationale"],
            cross_tier_confirmed=data.get("cross_tier_confirmed", False),
            cooldown_until=cooldown_until,
            status="active",
        )
        db.add(candidate)
        return candidate
