"""AnalystStyleSentimentEngine – fully local, deterministic, finance-aware.

Scoring formula:
  raw = base_tone + catalyst_boost - uncertainty_penalty - contradiction_penalty + intensity_boost
  score = clamp(raw, -1, +1)
  confidence = base_confidence * modifier
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.tables import NewsItem, SentimentScore
from app.modules.event_bus import event_bus

logger = logging.getLogger("sentiment_engine")


# ──────────────────────────────────────────────────────────────────────
# Narrative Tags
# ──────────────────────────────────────────────────────────────────────

class NarrativeTag(str, Enum):
    GUIDANCE_UP = "GUIDANCE_UP"
    GUIDANCE_DOWN = "GUIDANCE_DOWN"
    BEAT = "BEAT"
    MISS = "MISS"
    DOWNGRADE = "DOWNGRADE"
    UPGRADE = "UPGRADE"
    DOJ_PROBE = "DOJ_PROBE"
    SEC_PROBE = "SEC_PROBE"
    FDA_APPROVAL = "FDA_APPROVAL"
    FDA_REJECTION = "FDA_REJECTION"
    MARGIN_PRESSURE = "MARGIN_PRESSURE"
    MARGIN_EXPAND = "MARGIN_EXPAND"
    LAYOFFS = "LAYOFFS"
    DILUTION = "DILUTION"
    BUYBACK = "BUYBACK"
    ACQUISITION = "ACQUISITION"
    PRODUCT_DEMAND = "PRODUCT_DEMAND"
    MACRO_HEADWINDS = "MACRO_HEADWINDS"
    LIQUIDITY_RISK = "LIQUIDITY_RISK"
    DEFAULT_RISK = "DEFAULT_RISK"
    REVENUE_GROWTH = "REVENUE_GROWTH"
    REVENUE_DECLINE = "REVENUE_DECLINE"
    PARTNERSHIP = "PARTNERSHIP"
    LAWSUIT = "LAWSUIT"
    INSIDER_BUY = "INSIDER_BUY"
    INSIDER_SELL = "INSIDER_SELL"
    ANALYST_UPGRADE = "ANALYST_UPGRADE"
    ANALYST_DOWNGRADE = "ANALYST_DOWNGRADE"
    PRICE_TARGET_RAISE = "PRICE_TARGET_RAISE"
    PRICE_TARGET_CUT = "PRICE_TARGET_CUT"
    DIVIDEND_RAISE = "DIVIDEND_RAISE"
    DIVIDEND_CUT = "DIVIDEND_CUT"
    RESTRUCTURING = "RESTRUCTURING"


# ──────────────────────────────────────────────────────────────────────
# Lexicon + Phrase Patterns
# ──────────────────────────────────────────────────────────────────────

# (pattern, base_score, confidence_weight, tags)
CATALYST_PATTERNS: List[Tuple[str, float, float, List[NarrativeTag]]] = [
    # Earnings
    (r"\b(?:beats?|topped|surpass(?:es|ed)?|exceeded?)\s+(?:earnings?|estimates?|expectations?|consensus|EPS|forecasts?)", 0.55, 0.9, [NarrativeTag.BEAT]),
    (r"\b(?:miss(?:es|ed)?|fell short|below)\s+(?:earnings?|estimates?|expectations?|consensus|EPS|forecasts?)", -0.55, 0.9, [NarrativeTag.MISS]),
    (r"\b(?:blowout|blockbuster|stellar|record)\s+(?:earnings?|quarter|results?)", 0.6, 0.85, [NarrativeTag.BEAT]),
    (r"\b(?:disappointing|weak|dismal|poor)\s+(?:earnings?|quarter|results?)", -0.55, 0.85, [NarrativeTag.MISS]),

    # Guidance
    (r"\b(?:rais(?:es?|ed|ing)|hik(?:es?|ed|ing)|boost(?:s|ed)?|upward)\s+(?:guidance|outlook|forecast)", 0.5, 0.9, [NarrativeTag.GUIDANCE_UP]),
    (r"\b(?:lower(?:s|ed)?|cut(?:s)?|slash(?:es|ed)?|reduc(?:es?|ed|ing)|downward)\s+(?:guidance|outlook|forecast)", -0.55, 0.9, [NarrativeTag.GUIDANCE_DOWN]),
    (r"\b(?:warns?\s+(?:of|about)?|cautious\s+(?:guidance|outlook))", -0.4, 0.8, [NarrativeTag.GUIDANCE_DOWN]),

    # Analyst actions
    (r"\b(?:upgrade[sd]?)\s+(?:to\s+)?(?:buy|overweight|outperform)", 0.45, 0.85, [NarrativeTag.UPGRADE, NarrativeTag.ANALYST_UPGRADE]),
    (r"\b(?:downgrade[sd]?)\s+(?:to\s+)?(?:sell|underweight|underperform|neutral|hold)", -0.45, 0.85, [NarrativeTag.DOWNGRADE, NarrativeTag.ANALYST_DOWNGRADE]),
    (r"\b(?:rais(?:es?|ed|ing)|hik(?:es?|ed|ing))\s+(?:price\s+)?target", 0.35, 0.8, [NarrativeTag.PRICE_TARGET_RAISE]),
    (r"\b(?:cut(?:s)?|lower(?:s|ed)?|slash(?:es|ed)?)\s+(?:price\s+)?target", -0.35, 0.8, [NarrativeTag.PRICE_TARGET_CUT]),
    (r"\b(?:initiates?|starts?)\s+(?:coverage\s+)?(?:with\s+)?(?:buy|overweight|outperform)", 0.35, 0.75, [NarrativeTag.ANALYST_UPGRADE]),

    # Regulatory
    (r"\bFDA\s+(?:approv(?:es?|al|ed))", 0.65, 0.95, [NarrativeTag.FDA_APPROVAL]),
    (r"\bFDA\s+(?:reject(?:s|ed|ion)?|den(?:ies|ied|ial))", -0.65, 0.95, [NarrativeTag.FDA_REJECTION]),
    (r"\b(?:DOJ|department\s+of\s+justice)\s+(?:probe|investigat|lawsuit|charges?)", -0.5, 0.85, [NarrativeTag.DOJ_PROBE]),
    (r"\bSEC\s+(?:probe|investigat|charges?|lawsuit|enforcement)", -0.5, 0.85, [NarrativeTag.SEC_PROBE]),
    (r"\b(?:antitrust|anti-trust)\s+(?:probe|investigat|lawsuit|charges?)", -0.4, 0.8, [NarrativeTag.DOJ_PROBE]),

    # Corporate actions
    (r"\b(?:buyback|share\s+repurchas(?:e|es|ed|ing))", 0.3, 0.75, [NarrativeTag.BUYBACK]),
    (r"\b(?:dilution|dilutive|secondary\s+offering|stock\s+offering)", -0.35, 0.75, [NarrativeTag.DILUTION]),
    (r"\b(?:acquir(?:es?|ed|ing)|acquisition|buyout|takeover|merger)\b", 0.3, 0.7, [NarrativeTag.ACQUISITION]),
    (r"\b(?:layoff|laying\s+off|workforce\s+reduction|job\s+cuts?|headcount\s+reduction)", -0.3, 0.7, [NarrativeTag.LAYOFFS, NarrativeTag.RESTRUCTURING]),
    (r"\b(?:restructur(?:es?|ed|ing))", -0.15, 0.6, [NarrativeTag.RESTRUCTURING]),
    (r"\b(?:partnership|strategic\s+alliance|collaboration|joint\s+venture)", 0.3, 0.65, [NarrativeTag.PARTNERSHIP]),

    # Margins
    (r"\bmargin\s+(?:expansion|improv(?:es?|ed|ement|ing)|growth|widen(?:s|ed|ing)?)", 0.35, 0.8, [NarrativeTag.MARGIN_EXPAND]),
    (r"\bmargin\s+(?:pressure|compress(?:es?|ed|ion)|contraction|squeez(?:e|ed|ing)|declin(?:e|es?|ed|ing))", -0.35, 0.8, [NarrativeTag.MARGIN_PRESSURE]),

    # Revenue
    (r"\b(?:revenue|sales)\s+(?:surge[sd]?|soar(?:s|ed)?|jump(?:s|ed)?|growth|grew|climb(?:s|ed)?)", 0.4, 0.8, [NarrativeTag.REVENUE_GROWTH]),
    (r"\b(?:revenue|sales)\s+(?:decline[sd]?|drop(?:s|ped)?|plung(?:es?|ed)|fell|slip(?:s|ped)?|miss)", -0.4, 0.8, [NarrativeTag.REVENUE_DECLINE]),

    # Product demand
    (r"\b(?:record|strong|robust|surging?)\s+(?:demand|orders?|deliveries|shipments)", 0.35, 0.75, [NarrativeTag.PRODUCT_DEMAND]),
    (r"\b(?:weak|slowing|declining|falling)\s+(?:demand|orders?|deliveries|shipments)", -0.35, 0.75, [NarrativeTag.PRODUCT_DEMAND]),

    # Dividend
    (r"\b(?:rais(?:es?|ed)|hik(?:es?|ed)|boost(?:s|ed)?|increas(?:es?|ed))\s+(?:dividend|payout)", 0.25, 0.7, [NarrativeTag.DIVIDEND_RAISE]),
    (r"\b(?:cut(?:s)?|suspend(?:s|ed)?|eliminat(?:es?|ed)|slash(?:es|ed)?)\s+(?:dividend|payout)", -0.35, 0.75, [NarrativeTag.DIVIDEND_CUT]),

    # Macro
    (r"\b(?:recession|stagflation|trade\s+war|tariff(?:s)?|sanctions?)\b", -0.25, 0.6, [NarrativeTag.MACRO_HEADWINDS]),
    (r"\b(?:liquidity\s+(?:concern|crisis|crunch|risk))", -0.4, 0.75, [NarrativeTag.LIQUIDITY_RISK]),
    (r"\b(?:default(?:s|ed)?|bankruptcy|chapter\s+11|insolvency)", -0.7, 0.9, [NarrativeTag.DEFAULT_RISK]),

    # Insider
    (r"\b(?:insider|CEO|CFO|director)\s+(?:bought|buys?|purchas(?:es?|ed))", 0.25, 0.65, [NarrativeTag.INSIDER_BUY]),
    (r"\b(?:insider|CEO|CFO|director)\s+(?:sold|sells?|dump(?:s|ed)?)", -0.25, 0.65, [NarrativeTag.INSIDER_SELL]),

    # Lawsuits
    (r"\b(?:lawsuit|sued|litigation|legal\s+action|class\s+action)", -0.3, 0.7, [NarrativeTag.LAWSUIT]),
]

# General tone words (lower weight than catalysts)
BULLISH_WORDS: Dict[str, float] = {
    "surge": 0.25, "surges": 0.25, "surged": 0.25, "surging": 0.25,
    "soar": 0.25, "soars": 0.25, "soared": 0.25, "soaring": 0.25,
    "rally": 0.2, "rallies": 0.2, "rallied": 0.2, "rallying": 0.2,
    "jump": 0.2, "jumps": 0.2, "jumped": 0.2, "jumping": 0.2,
    "gain": 0.15, "gains": 0.15, "gained": 0.15,
    "rise": 0.15, "rises": 0.15, "rose": 0.15, "rising": 0.15,
    "climb": 0.15, "climbs": 0.15, "climbed": 0.15, "climbing": 0.15,
    "bullish": 0.3, "optimistic": 0.2, "upbeat": 0.2,
    "outperform": 0.25, "outperforms": 0.25,
    "breakout": 0.2, "breakthrough": 0.25,
    "strong": 0.15, "robust": 0.15, "solid": 0.1,
    "record": 0.15, "all-time high": 0.25, "new high": 0.2,
    "accelerat": 0.15, "momentum": 0.15, "boom": 0.2, "booming": 0.2,
    "profitable": 0.15, "profitability": 0.15,
    "innovation": 0.1, "innovative": 0.1,
}

BEARISH_WORDS: Dict[str, float] = {
    "crash": -0.3, "crashes": -0.3, "crashed": -0.3, "crashing": -0.3,
    "plunge": -0.3, "plunges": -0.3, "plunged": -0.3, "plunging": -0.3,
    "tumble": -0.25, "tumbles": -0.25, "tumbled": -0.25, "tumbling": -0.25,
    "sink": -0.2, "sinks": -0.2, "sank": -0.2, "sinking": -0.2,
    "drop": -0.2, "drops": -0.2, "dropped": -0.2, "dropping": -0.2,
    "decline": -0.2, "declines": -0.2, "declined": -0.2, "declining": -0.2,
    "fall": -0.15, "falls": -0.15, "fell": -0.15, "falling": -0.15,
    "slip": -0.15, "slips": -0.15, "slipped": -0.15, "slipping": -0.15,
    "bearish": -0.3, "pessimistic": -0.2, "cautious": -0.1,
    "underperform": -0.25, "underperforms": -0.25,
    "risk": -0.1, "risks": -0.1, "risky": -0.15,
    "concern": -0.1, "concerns": -0.1, "worried": -0.15, "worry": -0.1,
    "threat": -0.15, "threatens": -0.15,
    "loss": -0.15, "losses": -0.15,
    "weak": -0.15, "weakness": -0.15, "weakening": -0.15,
    "volatile": -0.1, "volatility": -0.1, "uncertainty": -0.1,
    "sell-off": -0.25, "selloff": -0.25,
    "headwind": -0.15, "headwinds": -0.15,
    "slowdown": -0.2, "slowing": -0.15,
    "warn": -0.15, "warns": -0.15, "warning": -0.15,
}

# Negation window
NEGATION_WORDS = {"not", "no", "never", "neither", "nor", "n't", "don't", "doesn't",
                  "didn't", "won't", "wouldn't", "shouldn't", "couldn't", "isn't",
                  "aren't", "wasn't", "weren't", "cannot", "hardly", "barely",
                  "scarcely", "no longer", "fail to", "fails to", "failed to"}

# Hedging / uncertainty modifiers
HEDGE_WORDS = {"may", "might", "could", "possibly", "perhaps", "reportedly",
               "allegedly", "rumored", "speculated", "potential", "potentially",
               "expected", "expects", "likely", "unlikely", "uncertain",
               "if", "whether", "seems", "appears"}

NEGATION_WINDOW = 4  # words


@dataclass
class SentimentResult:
    label: str = "neutral"
    score: float = 0.0
    confidence: float = 0.5
    intensity: float = 0.0
    narrative_tags: List[str] = field(default_factory=list)
    key_phrases: List[str] = field(default_factory=list)
    explanation: str = ""


class AnalystStyleSentimentEngine:
    """Deterministic finance-aware sentiment + catalyst engine."""

    def __init__(self) -> None:
        self._compiled_catalysts = [
            (re.compile(pat, re.IGNORECASE), score, conf, tags)
            for pat, score, conf, tags in CATALYST_PATTERNS
        ]

    def score(self, title: str, summary: str = "", text: str = "") -> SentimentResult:
        """Score a piece of news text. Returns SentimentResult."""
        combined = f"{title}. {summary}. {text}".strip()
        if not combined.strip(". "):
            return SentimentResult()

        words = re.findall(r"[\w'-]+", combined.lower())

        # 1. Catalyst pattern matching (highest priority)
        catalyst_score = 0.0
        catalyst_conf = 0.5
        all_tags: List[NarrativeTag] = []
        catalyst_phrases: List[str] = []
        explanation_parts: List[str] = []

        for pat, base_score, conf_w, tags in self._compiled_catalysts:
            matches = pat.findall(combined)
            if matches:
                # Check for negation in the surrounding context
                negated = self._check_negation_pattern(combined, pat)
                effective_score = -base_score * 0.8 if negated else base_score
                catalyst_score += effective_score
                catalyst_conf = max(catalyst_conf, conf_w)
                all_tags.extend(tags)
                phrase = matches[0] if isinstance(matches[0], str) else matches[0]
                catalyst_phrases.append(phrase.strip()[:80])
                direction = "NEGATED " if negated else ""
                explanation_parts.append(
                    f"{direction}catalyst '{phrase.strip()[:50]}' → {effective_score:+.2f}"
                )

        # 2. General tone word scoring
        base_tone = 0.0
        tone_phrases: List[str] = []
        negation_positions = self._find_negation_positions(words)

        for i, w in enumerate(words):
            in_negation = any(
                neg_pos < i <= neg_pos + NEGATION_WINDOW
                for neg_pos in negation_positions
            )
            if w in BULLISH_WORDS:
                val = BULLISH_WORDS[w]
                if in_negation:
                    val = -val * 0.7
                    tone_phrases.append(f"[negated]{w}")
                else:
                    tone_phrases.append(w)
                base_tone += val
            elif w in BEARISH_WORDS:
                val = BEARISH_WORDS[w]
                if in_negation:
                    val = -val * 0.7
                    tone_phrases.append(f"[negated]{w}")
                else:
                    tone_phrases.append(w)
                base_tone += val

        # Cap base_tone contribution
        base_tone = max(-0.5, min(0.5, base_tone))

        # 3. Hedging / uncertainty penalty
        hedge_count = sum(1 for w in words if w in HEDGE_WORDS)
        uncertainty_penalty = min(0.3, hedge_count * 0.05)

        # 4. Contradiction detection
        contradiction_penalty = 0.0
        has_bullish_catalyst = any(t.value in (
            "BEAT", "GUIDANCE_UP", "UPGRADE", "ANALYST_UPGRADE",
            "PRICE_TARGET_RAISE", "FDA_APPROVAL", "MARGIN_EXPAND",
            "REVENUE_GROWTH", "BUYBACK"
        ) for t in all_tags)
        has_bearish_catalyst = any(t.value in (
            "MISS", "GUIDANCE_DOWN", "DOWNGRADE", "ANALYST_DOWNGRADE",
            "PRICE_TARGET_CUT", "FDA_REJECTION", "MARGIN_PRESSURE",
            "REVENUE_DECLINE", "DILUTION", "DOJ_PROBE", "SEC_PROBE"
        ) for t in all_tags)
        if has_bullish_catalyst and has_bearish_catalyst:
            contradiction_penalty = 0.25
            explanation_parts.append("CONTRADICTION: mixed bullish+bearish catalysts → -0.25 penalty")

        # 5. Intensity boost (strong language)
        intensity_words = {"massive", "huge", "enormous", "significant",
                          "substantial", "dramatic", "sharp", "steep",
                          "record-breaking", "unprecedented", "historic",
                          "crushing", "devastating", "explosive", "monster"}
        intensity_count = sum(1 for w in words if w in intensity_words)
        intensity_boost = min(0.15, intensity_count * 0.05)

        # ── Final formula ──
        # Catalysts dominate when present; base_tone is secondary
        if catalyst_score != 0:
            raw = catalyst_score + base_tone * 0.3 + intensity_boost - uncertainty_penalty - contradiction_penalty
        else:
            raw = base_tone + intensity_boost - uncertainty_penalty - contradiction_penalty

        score = max(-1.0, min(1.0, raw))

        # Confidence
        if catalyst_score != 0:
            base_conf = catalyst_conf
        else:
            word_hits = len(tone_phrases)
            base_conf = min(0.85, 0.4 + word_hits * 0.08)

        confidence = max(0.1, base_conf - uncertainty_penalty * 0.5 - contradiction_penalty * 0.4)

        # Intensity
        intensity = min(1.0, abs(score) + intensity_boost + (0.2 if catalyst_score != 0 else 0))

        # Label
        if score > 0.05:
            label = "bullish"
        elif score < -0.05:
            label = "bearish"
        else:
            label = "neutral"

        # Build explanation
        if base_tone != 0:
            explanation_parts.append(f"base_tone={base_tone:+.3f}")
        if uncertainty_penalty > 0:
            explanation_parts.append(f"uncertainty_penalty=-{uncertainty_penalty:.3f}")
        if intensity_boost > 0:
            explanation_parts.append(f"intensity_boost=+{intensity_boost:.3f}")
        explanation_parts.append(f"final_score={score:+.3f}, conf={confidence:.3f}")

        unique_tags = list(dict.fromkeys(t.value for t in all_tags))
        all_phrases = catalyst_phrases + tone_phrases[:10]

        return SentimentResult(
            label=label,
            score=round(score, 4),
            confidence=round(confidence, 4),
            intensity=round(intensity, 4),
            narrative_tags=unique_tags,
            key_phrases=all_phrases[:15],
            explanation="; ".join(explanation_parts),
        )

    def _find_negation_positions(self, words: List[str]) -> List[int]:
        """Find word indices that are negation triggers."""
        positions = []
        for i, w in enumerate(words):
            if w in NEGATION_WORDS:
                positions.append(i)
            # Two-word negations
            if i > 0:
                bigram = f"{words[i-1]} {w}"
                if bigram in NEGATION_WORDS:
                    positions.append(i)
        return positions

    def _check_negation_pattern(self, text: str, pattern: re.Pattern) -> bool:
        """Check if a catalyst pattern match is preceded by negation."""
        match = pattern.search(text)
        if not match:
            return False
        start = max(0, match.start() - 60)
        prefix = text[start:match.start()].lower()
        prefix_words = re.findall(r"[\w'-]+", prefix)
        # Only look at last NEGATION_WINDOW words before the match
        window = prefix_words[-NEGATION_WINDOW:]
        return any(w in NEGATION_WORDS for w in window)

    async def analyze_news(self, news_item: NewsItem, ticker: str) -> Optional[SentimentScore]:
        """Score a news item for a specific ticker and persist."""
        result = self.score(
            title=news_item.title or "",
            summary=news_item.summary or "",
            text=news_item.text or "",
        )

        db: Session = SessionLocal()
        try:
            ss = SentimentScore(
                news_id=news_item.id,
                ticker=ticker,
                label=result.label,
                score=result.score,
                confidence=result.confidence,
                intensity=result.intensity,
                narrative_tags=result.narrative_tags,
                key_phrases=result.key_phrases,
                explanation=result.explanation,
            )
            db.add(ss)
            db.commit()
            db.refresh(ss)

            await event_bus.emit(
                "SENTIMENT_SCORED", "sentiment_engine",
                ticker=ticker,
                payload={
                    "news_id": news_item.id,
                    "ticker": ticker,
                    "label": result.label,
                    "score": result.score,
                    "confidence": result.confidence,
                    "intensity": result.intensity,
                    "tags": result.narrative_tags,
                    "key_phrases": result.key_phrases[:5],
                    "explanation": result.explanation[:300],
                    "title": (news_item.title or "")[:150],
                },
            )
            return ss
        finally:
            db.close()
