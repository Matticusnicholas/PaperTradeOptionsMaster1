"""TickerResolver – map news items to tickers using watchlist aliases."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from app.config import WATCHLIST
from app.database import SessionLocal
from app.models.tables import NewsItem, TickerMention
from app.modules.event_bus import event_bus

logger = logging.getLogger("ticker_resolver")


class TickerResolver:
    """Heuristic entity matching: scans title+summary for watchlist aliases."""

    def __init__(self) -> None:
        self.watchlist: Dict[str, List[str]] = WATCHLIST
        # Pre-compile patterns per ticker for speed
        self._patterns: Dict[str, List[Tuple[re.Pattern, str]]] = {}
        for ticker, aliases in self.watchlist.items():
            pats = []
            for alias in aliases:
                # Word boundary match, case-insensitive
                pat = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
                pats.append((pat, alias))
            # Also match $TICKER
            pats.append((re.compile(r"\$" + re.escape(ticker) + r"\b", re.IGNORECASE), f"${ticker}"))
            self._patterns[ticker] = pats

    async def resolve(self, news_item: NewsItem) -> List[TickerMention]:
        """Find all matching tickers in a news item."""
        text = f"{news_item.title or ''} {news_item.summary or ''} {news_item.text or ''}"
        results: List[TickerMention] = []
        db: Session = SessionLocal()
        try:
            for ticker, pats in self._patterns.items():
                matched_aliases = []
                total_matches = 0
                for pat, alias in pats:
                    hits = pat.findall(text)
                    if hits:
                        matched_aliases.append(alias)
                        total_matches += len(hits)

                if not matched_aliases:
                    continue

                # Relevance: more matches / aliases = higher
                relevance = min(1.0, 0.3 + 0.15 * total_matches + 0.2 * len(matched_aliases))

                # Check for ticker in title (title-mention boost)
                title_text = news_item.title or ""
                for pat, _alias in pats:
                    if pat.search(title_text):
                        relevance = min(1.0, relevance + 0.2)
                        break

                mention = TickerMention(
                    news_id=news_item.id,
                    ticker=ticker,
                    relevance=round(relevance, 3),
                    matched_aliases=matched_aliases,
                )
                db.add(mention)
                results.append(mention)

            if results:
                db.commit()
                for m in results:
                    db.refresh(m)
                    await event_bus.emit(
                        "TICKER_RESOLVED", "ticker_resolver",
                        ticker=m.ticker,
                        payload={
                            "news_id": news_item.id,
                            "ticker": m.ticker,
                            "relevance": m.relevance,
                            "matched_aliases": m.matched_aliases,
                            "title": (news_item.title or "")[:150],
                        },
                    )
        finally:
            db.close()
        return results
