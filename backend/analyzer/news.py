"""
News & injury search via DuckDuckGo HTML scraping.
No API key required.
"""

import logging
import re
from datetime import date
from scrapling.fetchers import Fetcher

log = logging.getLogger(__name__)

DDG_URL = "https://html.duckduckgo.com/html/"
INJURY_KEYWORDS = [
    "injured", "injury", "doubt", "ruled out", "suspended", "suspension",
    "unavailable", "miss", "missing", "out",
    "povređen", "povreda", "suspenzija", "upitan", "nedostupan", "neće nastupiti",
]


def search_match_news(home_team: str, away_team: str, league: str = "") -> list[dict]:
    """
    Search for injury/team news for a match.
    Returns list of news items with title and relevance.
    """
    queries = [
        f"{home_team} {away_team} injury team news",
        f"{home_team} missing players suspended",
        f"{away_team} missing players suspended",
    ]

    all_news = []
    for query in queries:
        results = _ddg_search(query)
        all_news.extend(results)

    # Deduplicate by title snippet
    seen = set()
    unique_news = []
    for item in all_news:
        key = item["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique_news.append(item)

    return unique_news[:8]  # Return top 8 relevant results


def _ddg_search(query: str) -> list[dict]:
    """Perform a DuckDuckGo HTML search and return result snippets."""
    try:
        import httpx
        resp = httpx.post(
            DDG_URL,
            data={"q": query, "kl": "us-en"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            follow_redirects=True,
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        # Parse with Scrapling's Fetcher (parse-only mode)
        from scrapling import Fetcher
        page = Fetcher.fetch(DDG_URL)

        # Actually parse the response HTML directly
        from scrapling import Adaptor
        doc = Adaptor(resp.text)

        results = []
        result_divs = doc.find_all("div", {"class": re.compile(r"result|web-result", re.I)})
        for div in result_divs[:5]:
            title_el = div.find("a", {"class": re.compile(r"result__a|result-link", re.I)})
            snippet_el = div.find("a", {"class": re.compile(r"result__snippet|snippet", re.I)})
            if not title_el:
                continue
            title = (title_el.text or "").strip()
            snippet = (snippet_el.text or "").strip() if snippet_el else ""

            # Only include if contains injury-related keywords
            combined = (title + " " + snippet).lower()
            is_relevant = any(kw in combined for kw in INJURY_KEYWORDS)

            results.append({
                "title": title,
                "snippet": snippet,
                "relevant": is_relevant,
                "query": query,
            })

        return [r for r in results if r["relevant"]]

    except Exception as e:
        log.warning(f"DDG search failed for '{query}': {e}")
        return []


def extract_injury_summary(news_items: list[dict], home_team: str, away_team: str) -> dict:
    """
    Parse news items and extract structured injury info.
    Returns: {home_missing: [...], away_missing: [...], notes: [...]}
    """
    home_missing = []
    away_missing = []
    notes = []

    for item in news_items:
        text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
        is_home = home_team.lower()[:6] in text
        is_away = away_team.lower()[:6] in text

        # Try to extract player name (capitalized words near injury keywords)
        player_match = re.search(
            r"([A-Z][a-z]+ [A-Z][a-z]+)\s+(?:is|has been|ruled out|injured|suspended)",
            item.get("title", "") + " " + item.get("snippet", "")
        )
        player_name = player_match.group(1) if player_match else None

        snippet = item.get("snippet") or item.get("title", "")
        if len(snippet) > 120:
            snippet = snippet[:120] + "..."

        if any(kw in text for kw in ["ruled out", "injured", "miss", "missing", "unavailable", "suspended"]):
            if is_home and player_name:
                home_missing.append(player_name)
            if is_away and player_name:
                away_missing.append(player_name)
            notes.append(snippet)

    return {
        "home_missing": list(set(home_missing)),
        "away_missing": list(set(away_missing)),
        "notes": notes[:4],
    }
