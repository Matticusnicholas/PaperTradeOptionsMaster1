"""Unit tests for AnalystStyleSentimentEngine – negation, hedging, contradiction."""

import pytest
from app.modules.sentiment_engine import AnalystStyleSentimentEngine, SentimentResult


@pytest.fixture
def engine():
    return AnalystStyleSentimentEngine()


class TestBasicSentiment:
    def test_bullish_beat(self, engine):
        r = engine.score("Apple beats earnings expectations with record revenue")
        assert r.label == "bullish"
        assert r.score > 0.3
        assert r.confidence > 0.7
        assert "BEAT" in r.narrative_tags

    def test_bearish_miss(self, engine):
        r = engine.score("Tesla misses earnings estimates, revenue falls short")
        assert r.label == "bearish"
        assert r.score < -0.3
        assert "MISS" in r.narrative_tags

    def test_neutral_generic(self, engine):
        r = engine.score("Company announces quarterly report date")
        assert abs(r.score) < 0.3

    def test_strong_bullish_guidance_up(self, engine):
        r = engine.score("NVDA raises guidance and boosts outlook for AI demand")
        assert r.label == "bullish"
        assert r.score > 0.3
        assert "GUIDANCE_UP" in r.narrative_tags

    def test_bearish_guidance_down(self, engine):
        r = engine.score("Microsoft lowers guidance amid slowing cloud growth")
        assert r.label == "bearish"
        assert r.score < -0.3
        assert "GUIDANCE_DOWN" in r.narrative_tags


class TestNegation:
    def test_negated_bullish(self, engine):
        """'not strong' should reduce bullish signal."""
        r_positive = engine.score("Strong demand drives revenue growth")
        r_negated = engine.score("Not strong demand fails to drive revenue growth")
        assert r_negated.score < r_positive.score

    def test_negated_beat(self, engine):
        """'did not beat' should flip or reduce."""
        r = engine.score("Company did not beat earnings expectations")
        # Should not be strongly bullish
        assert r.score < 0.2

    def test_no_longer_positive(self, engine):
        r = engine.score("Analysts no longer see bullish momentum for the stock")
        # Should have reduced bullish signal
        assert r.score <= 0.1

    def test_double_negation(self, engine):
        """'not unlikely' should be less negative than 'unlikely'."""
        r_neg = engine.score("Recovery is unlikely for the company")
        r_double = engine.score("Recovery is not unlikely for the company")
        assert r_double.score >= r_neg.score


class TestHedging:
    def test_hedging_reduces_confidence(self, engine):
        """Hedging words should reduce confidence."""
        r_direct = engine.score("Apple beats earnings with record revenue")
        r_hedged = engine.score("Apple may possibly beat earnings expectations")
        assert r_hedged.confidence < r_direct.confidence

    def test_reportedly_qualifier(self, engine):
        r = engine.score("Company reportedly plans massive layoffs")
        assert r.confidence < 0.9  # should be discounted

    def test_expected_qualifier(self, engine):
        r = engine.score("Revenue growth is expected to accelerate")
        # Still bullish but with uncertainty discount
        assert r.label == "bullish"


class TestContradiction:
    def test_beat_but_lower_guidance(self, engine):
        """Mixed signal: beat + lower guidance → contradiction penalty."""
        r = engine.score("Apple beats earnings but lowers guidance for next quarter")
        assert "BEAT" in r.narrative_tags
        assert "GUIDANCE_DOWN" in r.narrative_tags
        # Score should be dampened due to contradiction
        assert abs(r.score) < 0.5
        assert "CONTRADICTION" in r.explanation.upper()

    def test_upgrade_but_concern(self, engine):
        r = engine.score(
            "Analyst upgrades to buy but warns of margin pressure headwinds"
        )
        # Mixed signal → contradiction penalty applied, should be moderated
        assert abs(r.score) < 0.8
        assert "CONTRADICTION" in r.explanation.upper()


class TestCatalystTags:
    def test_fda_approval(self, engine):
        r = engine.score("FDA approves new drug treatment from Pfizer")
        assert "FDA_APPROVAL" in r.narrative_tags
        assert r.label == "bullish"
        assert r.score > 0.4

    def test_fda_rejection(self, engine):
        r = engine.score("FDA rejects application for new cancer treatment")
        assert "FDA_REJECTION" in r.narrative_tags
        assert r.label == "bearish"
        assert r.score < -0.4

    def test_doj_probe(self, engine):
        r = engine.score("DOJ probe into Google's advertising practices intensifies")
        assert "DOJ_PROBE" in r.narrative_tags
        assert r.label == "bearish"

    def test_buyback(self, engine):
        r = engine.score("Apple announces $90 billion share buyback program")
        assert "BUYBACK" in r.narrative_tags
        assert r.label == "bullish"

    def test_layoffs(self, engine):
        r = engine.score("Meta announces massive layoffs cutting 10000 jobs")
        assert "LAYOFFS" in r.narrative_tags
        assert r.label == "bearish"

    def test_acquisition(self, engine):
        r = engine.score("Microsoft acquires gaming company in $70 billion deal")
        assert "ACQUISITION" in r.narrative_tags

    def test_default_risk(self, engine):
        r = engine.score("Company faces bankruptcy and chapter 11 proceedings")
        assert "DEFAULT_RISK" in r.narrative_tags
        assert r.score < -0.5
        assert r.confidence > 0.7


class TestIntensity:
    def test_intense_language(self, engine):
        r = engine.score("Massive unprecedented surge in revenue growth")
        assert r.intensity > 0.5

    def test_mild_language(self, engine):
        r = engine.score("Revenue showed slight increase")
        assert r.intensity < 0.7
