"""
Aggregates data from FlashScore (+ SofaScore, LiveScore) into unified match objects.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .flashscore import (
    scrape_today_matches,
    scrape_recent_matches,
    scrape_match_details,
    scrape_team_form,
    scrape_h2h,
    scrape_league_standings,
    scrape_match_odds,
    _fetch,
)
from .sofascore import scrape_live_stats as sofa_live_stats
from .livescore import scrape_live_stats as live_live_stats

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=6)


def _run(fn, *args, **kwargs):
    future = _executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=90)
    except Exception as e:
        log.warning(f"Thread failed {fn.__name__}: {e}")
        return None


# ─── STANDINGS CACHE (po pozivu — jedna liga jednom) ──────────────────────────

_standings_cache: dict[str, dict] = {}


def _get_standings(league_url: str) -> dict:
    if not league_url:
        return {}
    if league_url in _standings_cache:
        return _standings_cache[league_url]
    standings = _run(scrape_league_standings, league_url) or {}
    _standings_cache[league_url] = standings
    return standings


# ─── MAIN ENTRY ───────────────────────────────────────────────────────────────

def get_all_matches() -> list[dict]:
    """Sve fudbalske utakmice (upcoming + live) sa FlashScore-a."""
    result = _run(scrape_today_matches)
    if not result:
        log.warning("No matches returned from FlashScore")
        return []

    matches, league_urls = result
    # league_urls je {league_name: url} — osvezi standings cache u backgroundu
    # (ne cekamo, standings se lazy-load tokom enrichmenta)
    return matches


# ─── QUICK ANALYSIS ENRICH (za background loop) ───────────────────────────────

def enrich_for_analysis(match: dict) -> dict:
    """
    Light enrichment za automatsku analizu: recent_5 za oba tima + standings + odds.
    Bez modalnih detalja. Brže od pune enrichment.
    """
    enriched = dict(match)
    home      = match["home_team"]
    away      = match["away_team"]
    match_url = match.get("match_url", "")
    league_url = match.get("league_url", "")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}

        # Standings za ligu
        if league_url:
            futures["standings"] = pool.submit(_get_standings, league_url)

        # Team URLs
        home_url = _find_team_url(home, match_url)
        away_url = _find_team_url(away, match_url)

        if home_url:
            futures["home_recent_5"] = pool.submit(scrape_recent_matches, home, home_url, 5)
        if away_url:
            futures["away_recent_5"] = pool.submit(scrape_recent_matches, away, away_url, 5)

        # Odds (samo za predstojece)
        if match.get("status") == "upcoming" and match_url:
            futures["odds"] = pool.submit(scrape_match_odds, match_url)

        for key, fut in futures.items():
            try:
                res = fut.result(timeout=60)
                if res:
                    enriched[key] = res
            except Exception as e:
                log.debug(f"enrich_for_analysis {key}: {e}")

    # Popuni opponent_position u recent_5 koristeci standings
    standings = enriched.get("standings") or {}
    for side in ["home_recent_5", "away_recent_5"]:
        for m in enriched.get(side) or []:
            if m.get("opponent_position", 0) == 0 and standings:
                m["opponent_position"] = _lookup_position(m.get("opponent", ""), standings)

    return enriched


# ─── FULL MODAL ENRICH ────────────────────────────────────────────────────────

def enrich_match(match: dict) -> dict:
    """
    Puna enrichment za modal: form tabele, H2H, statistika, live stats.
    """
    enriched = dict(match)
    home      = match["home_team"]
    away      = match["away_team"]
    match_url = match.get("match_url", "")
    league_url = match.get("league_url", "")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}

        if match_url:
            futures["match_details"] = pool.submit(scrape_match_details, match_url)
            futures["h2h"]           = pool.submit(scrape_h2h, match_url)
            futures["odds"]          = pool.submit(scrape_match_odds, match_url)

        if league_url:
            futures["standings"] = pool.submit(_get_standings, league_url)

        home_url = _find_team_url(home, match_url)
        away_url = _find_team_url(away, match_url)

        if home_url:
            futures["home_recent_5"]   = pool.submit(scrape_recent_matches, home, home_url, 5)
            futures["home_form_home"]  = pool.submit(scrape_team_form, home, home_url, "home")
            futures["home_form_away"]  = pool.submit(scrape_team_form, home, home_url, "away")
        if away_url:
            futures["away_recent_5"]   = pool.submit(scrape_recent_matches, away, away_url, 5)
            futures["away_form_home"]  = pool.submit(scrape_team_form, away, away_url, "home")
            futures["away_form_away"]  = pool.submit(scrape_team_form, away, away_url, "away")

        if match.get("status") == "live":
            futures["sofa_stats"] = pool.submit(sofa_live_stats, home, away)
            futures["ls_stats"]   = pool.submit(live_live_stats, home, away)

        for key, fut in futures.items():
            try:
                res = fut.result(timeout=60)
                if res:
                    enriched[key] = res
            except Exception as e:
                log.warning(f"Enrichment {key}: {e}")

    # Standings → opponent positions
    standings = enriched.get("standings") or {}
    for side in ["home_recent_5", "away_recent_5"]:
        for m in enriched.get(side) or []:
            if m.get("opponent_position", 0) == 0 and standings:
                m["opponent_position"] = _lookup_position(m.get("opponent", ""), standings)

    enriched["stats"] = _merge_stats(enriched)

    for form_key in ["home_form_home", "home_form_away", "away_form_home", "away_form_away"]:
        if form_key in enriched and isinstance(enriched[form_key], list):
            enriched[f"{form_key}_summary"] = _summarize_form(enriched[form_key])

    return enriched


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _lookup_position(opponent: str, standings: dict) -> int:
    """Traži poziciju tima u tabeli — partial match na lowercase."""
    if not opponent or not standings:
        return 0
    opp_lower = opponent.lower().strip()
    # Exact match
    if opp_lower in standings:
        return standings[opp_lower]
    # Partial match (first 6 chars)
    prefix = opp_lower[:6]
    for name, pos in standings.items():
        if prefix in name or name[:6] in opp_lower:
            return pos
    return 0


def _find_team_url(team_name: str, match_url: str) -> Optional[str]:
    """Pronalazi URL tima sa stranice utakmice."""
    if not match_url:
        return None
    try:
        page = _fetch(match_url, timeout=25000)
        if page is None:
            return None
        team_slug = team_name.lower().replace(" ", "-")[:8]
        for el in page.css('a[href*="/team/"]'):
            href = el.attrib.get("href", "")
            if team_slug in href.lower():
                base = "https://www.flashscore.com"
                return base + href if not href.startswith("http") else href
        # Fallback — prvi /team/ link
        links = page.css('a[href*="/team/"]')
        if links:
            href = links[0].attrib.get("href", "")
            base = "https://www.flashscore.com"
            return base + href if not href.startswith("http") else href
    except Exception as e:
        log.debug(f"Team URL not found for {team_name}: {e}")
    return None


def _merge_stats(match: dict) -> dict:
    base   = (match.get("match_details") or {}).get("stats", {})
    sofa   = match.get("sofa_stats") or {}
    ls     = match.get("ls_stats") or {}
    merged = dict(base)
    for key in ["xg", "possession", "shots_on_target", "shots_total", "corners", "yellow_cards", "red_cards"]:
        if key in sofa:
            merged[key] = sofa[key]
        elif key in ls and key not in merged:
            merged[key] = ls[key]
    return merged


def _summarize_form(matches: list[dict]) -> dict:
    if not matches:
        return {}
    wins       = sum(1 for m in matches if m.get("result") == "W")
    draws      = sum(1 for m in matches if m.get("result") == "D")
    losses     = sum(1 for m in matches if m.get("result") == "L")
    scored     = [m.get("goals_scored", 0) for m in matches]
    conceded   = [m.get("goals_conceded", 0) for m in matches]
    btts_count = sum(1 for m in matches if m.get("btts", False))
    over25     = sum(1 for m in matches if (m.get("total_goals", 0) or 0) > 2)
    n          = len(matches)
    return {
        "wins":          wins,
        "draws":         draws,
        "losses":        losses,
        "avg_scored":    round(sum(scored) / n, 2),
        "avg_conceded":  round(sum(conceded) / n, 2),
        "btts_count":    btts_count,
        "over25_count":  over25,
        "form_string":   "".join(m.get("result", "?") for m in matches),
        "matches":       matches,
    }
