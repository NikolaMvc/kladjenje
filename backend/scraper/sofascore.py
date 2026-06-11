"""
SofaScore DOM scraper — supplements FlashScore with xG, possession, advanced stats.
Uses DynamicFetcher (Playwright) since site is React-rendered.
"""

import logging
import re
from scrapling.fetchers import DynamicFetcher, StealthyFetcher

log = logging.getLogger(__name__)

BASE_URL = "https://www.sofascore.com"


def _fetch(url: str, timeout: int = 35000):
    try:
        return StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=timeout)
    except Exception as e:
        log.warning(f"SofaScore StealthyFetcher failed: {e}")
    try:
        return DynamicFetcher.fetch(url, network_idle=True, timeout=timeout)
    except Exception as e:
        log.error(f"SofaScore DynamicFetcher failed: {e}")
        return None


def _safe_text(el) -> str:
    try:
        return (el.text or "").strip()
    except Exception:
        return ""


def scrape_live_stats(home_team: str, away_team: str) -> dict:
    """
    Search SofaScore for the live match and return advanced stats.
    Returns dict with xg, possession, shots, etc.
    """
    page = _fetch(f"{BASE_URL}/", timeout=40000)
    if page is None:
        return {}

    # Find the match link by team names
    match_link = None
    all_links = page.find_all("a", {"href": re.compile(r"/event/")})
    for link in all_links:
        text = _safe_text(link).lower()
        if home_team.lower()[:5] in text and away_team.lower()[:5] in text:
            match_link = link.attrib.get("href", "")
            break

    if not match_link:
        return {}

    match_url = BASE_URL + match_link + "#statistics"
    stats_page = _fetch(match_url, timeout=35000)
    if stats_page is None:
        return {}

    return _parse_stats_page(stats_page)


def _parse_stats_page(page) -> dict:
    stats = {}

    stat_rows = page.find_all("div", {"class": re.compile(r"stat|statistic|statisticRow", re.I)})
    for row in stat_rows:
        try:
            category_el = row.find("span", {"class": re.compile(r"category|statTitle|statLabel", re.I)})
            home_el = row.find("span", {"class": re.compile(r"home|left", re.I)})
            away_el = row.find("span", {"class": re.compile(r"away|right", re.I)})

            if not category_el:
                continue
            name = _safe_text(category_el).lower()
            hv = _safe_text(home_el)
            av = _safe_text(away_el)

            def _num(s):
                s = s.replace("%", "").strip()
                try:
                    return float(s)
                except Exception:
                    return 0.0

            if "xg" in name or "expected" in name:
                stats["xg"] = {"home": _num(hv), "away": _num(av)}
            elif "possession" in name:
                stats["possession"] = {"home": _num(hv), "away": _num(av)}
            elif "shots on" in name or "on target" in name:
                stats["shots_on_target"] = {"home": int(_num(hv)), "away": int(_num(av))}
            elif "shots" in name:
                stats["shots_total"] = {"home": int(_num(hv)), "away": int(_num(av))}
            elif "corner" in name:
                stats["corners"] = {"home": int(_num(hv)), "away": int(_num(av))}
            elif "yellow" in name:
                stats["yellow_cards"] = {"home": int(_num(hv)), "away": int(_num(av))}
            elif "red" in name:
                stats["red_cards"] = {"home": int(_num(hv)), "away": int(_num(av))}
        except Exception:
            continue

    return stats


def scrape_team_form_sofascore(team_name: str) -> list[dict]:
    """
    Get last matches for a team from SofaScore as supplementary data.
    """
    # Search for team page
    search_url = f"{BASE_URL}/search/{team_name.replace(' ', '%20')}"
    page = _fetch(search_url, timeout=30000)
    if page is None:
        return []

    team_link = None
    links = page.find_all("a", {"href": re.compile(r"/team/")})
    for link in links:
        if team_name.lower()[:6] in _safe_text(link).lower():
            team_link = link.attrib.get("href", "")
            break

    if not team_link:
        return []

    team_page = _fetch(BASE_URL + team_link + "/matches/", timeout=30000)
    if team_page is None:
        return []

    results = []
    match_rows = page.find_all("div", {"class": re.compile(r"matchRow|eventRow", re.I)})
    for row in match_rows[:10]:
        try:
            score_el = row.find("span", {"class": re.compile(r"score", re.I)})
            if not score_el:
                continue
            score_text = _safe_text(score_el)
            parts = re.split(r"[-:]", score_text)
            if len(parts) < 2:
                continue
            results.append({
                "score": score_text,
                "score_home": int(re.sub(r"\D", "", parts[0]) or 0),
                "score_away": int(re.sub(r"\D", "", parts[1]) or 0),
            })
        except Exception:
            continue

    return results
