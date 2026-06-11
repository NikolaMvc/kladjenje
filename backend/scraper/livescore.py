"""
LiveScore DOM scraper — tertiary source for match data verification.
Simpler site structure, good fallback.
"""

import logging
import re
from scrapling.fetchers import DynamicFetcher, StealthyFetcher

log = logging.getLogger(__name__)

BASE_URL = "https://www.livescore.com/en"


def _fetch(url: str, timeout: int = 30000):
    try:
        return StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=timeout)
    except Exception as e:
        log.warning(f"LiveScore fetch failed: {e}")
    try:
        return DynamicFetcher.fetch(url, network_idle=True, timeout=timeout)
    except Exception as e:
        log.error(f"LiveScore DynamicFetcher failed: {e}")
        return None


def _safe_text(el) -> str:
    try:
        return (el.text or "").strip()
    except Exception:
        return ""


def scrape_matches() -> list[dict]:
    """Return today's football matches from LiveScore as supplementary list."""
    page = _fetch(f"{BASE_URL}/football/", timeout=35000)
    if page is None:
        return []

    matches = []

    # LiveScore renders match containers with class patterns like "row" or "match"
    rows = page.find_all("div", {"class": re.compile(r"match|event|fixture", re.I)})

    for row in rows:
        try:
            home_el = row.find("span", {"class": re.compile(r"home|team-home|participant", re.I)})
            away_el = row.find("span", {"class": re.compile(r"away|team-away|participant", re.I)})
            if not home_el or not away_el:
                continue

            home = _safe_text(home_el)
            away = _safe_text(away_el)
            if not home or not away or home == away:
                continue

            score_els = row.find_all("span", {"class": re.compile(r"score|goal", re.I)})
            score_home = None
            score_away = None
            if len(score_els) >= 2:
                sh = _safe_text(score_els[0])
                sa = _safe_text(score_els[1])
                if sh.isdigit() and sa.isdigit():
                    score_home = int(sh)
                    score_away = int(sa)

            time_el = row.find("span", {"class": re.compile(r"time|minute|clock", re.I)})
            time_text = _safe_text(time_el) if time_el else ""

            is_live = bool(re.search(r"\d+['']", time_text))
            status = "live" if is_live else "upcoming"

            matches.append({
                "source": "livescore",
                "home_team": home,
                "away_team": away,
                "status": status,
                "score": {"home": score_home, "away": score_away} if score_home is not None else None,
                "time_text": time_text,
            })
        except Exception:
            continue

    log.info(f"LiveScore: found {len(matches)} matches")
    return matches


def scrape_live_stats(home_team: str, away_team: str) -> dict:
    """
    Try to get live stats from LiveScore for a specific match.
    Returns basic stats dict.
    """
    page = _fetch(f"{BASE_URL}/football/", timeout=30000)
    if page is None:
        return {}

    # Find match row matching these teams
    rows = page.find_all("div", {"class": re.compile(r"match|event|fixture", re.I)})
    match_url = None

    for row in rows:
        text = (row.text or "").lower()
        if home_team.lower()[:5] in text and away_team.lower()[:5] in text:
            link = row.find("a", {"href": re.compile(r"/football/")})
            if link:
                match_url = BASE_URL + link.attrib.get("href", "")
            break

    if not match_url:
        return {}

    match_page = _fetch(match_url, timeout=30000)
    if not match_page:
        return {}

    stats = {}
    stat_rows = match_page.find_all("div", {"class": re.compile(r"stat|statistic", re.I)})
    for stat_row in stat_rows:
        try:
            text = (stat_row.text or "").lower()
            nums = re.findall(r"\d+\.?\d*", stat_row.text or "")
            if "possession" in text and len(nums) >= 2:
                stats["possession"] = {"home": float(nums[0]), "away": float(nums[1])}
            elif "corner" in text and len(nums) >= 2:
                stats["corners"] = {"home": int(nums[0]), "away": int(nums[1])}
        except Exception:
            continue

    return stats
