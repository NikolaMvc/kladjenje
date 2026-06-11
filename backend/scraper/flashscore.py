"""
FlashScore DOM scraper — DynamicFetcher (Playwright).
Proverenа struktura: event__homeParticipant, event__awayParticipant, event__score--home/away
"""

import logging
import re
from datetime import date
from typing import Optional
from scrapling.fetchers import DynamicFetcher

log = logging.getLogger(__name__)
BASE_URL = "https://www.flashscore.com"
FOOTBALL_URL = f"{BASE_URL}/football/"


def _fetch(url: str, timeout: int = 50000):
    try:
        return DynamicFetcher.fetch(url, network_idle=True, timeout=timeout)
    except Exception as e:
        log.error(f"DynamicFetcher failed {url}: {e}")
        return None


def _get_name(row, selector: str) -> str:
    els = row.css(selector)
    if not els:
        return ""
    for child in els[0].find_all("*"):
        t = (child.text or "").strip()
        if t:
            return t
    return (els[0].text or "").strip()


def _get_txt(row, selector: str) -> str:
    els = row.css(selector)
    if not els:
        return ""
    t = (els[0].text or "").strip()
    if t:
        return t
    for child in els[0].find_all("*"):
        t = (child.text or "").strip()
        if t:
            return t
    return ""


# ─── MAIN MATCHES LIST ─────────────────────────────────────────────────────────

def scrape_today_matches() -> tuple[list[dict], dict]:
    """
    Sve fudbalske utakmice za danas.
    Vraća (matches, league_urls) gde league_urls = {league_name: url}.
    """
    page = _fetch(FOOTBALL_URL, timeout=55000)
    if page is None:
        return [], {}

    matches    = []
    league_map, league_urls = _build_league_map(page)

    rows = page.css('[id^="g_1_"]')
    log.info(f"FlashScore: {len(rows)} elemenata u DOM-u")

    for row in rows:
        try:
            match_id  = (row.attrib.get("id") or "").replace("g_1_", "")
            if not match_id:
                continue

            row_class = row.attrib.get("class") or ""

            home_team = _get_name(row, '[class*="event__homeParticipant"]')
            away_team = _get_name(row, '[class*="event__awayParticipant"]')
            if not home_team or not away_team:
                continue

            sh = _get_txt(row, '[class*="event__score--home"]')
            sa = _get_txt(row, '[class*="event__score--away"]')
            score_home = int(sh) if sh.isdigit() else None
            score_away = int(sa) if sa.isdigit() else None

            is_live     = "event__match--live"      in row_class
            is_scheduled = "event__match--scheduled" in row_class

            minute      = None
            kickoff_iso = None

            if is_live:
                stage = _get_txt(row, '[class*="event__stage"]')
                m = re.search(r"(\d+)", stage)
                if m:
                    minute = int(m.group(1))
            elif is_scheduled:
                t = _get_txt(row, '[class*="event__time"]')
                if re.match(r"\d{1,2}:\d{2}", t):
                    kickoff_iso = f"{date.today().isoformat()}T{t.zfill(5)}:00"

            status = "live" if is_live else ("upcoming" if is_scheduled else "finished")

            league     = league_map.get(match_id, "Football")
            league_url = league_urls.get(league)

            matches.append({
                "id":         f"fs_{match_id}",
                "source":     "flashscore",
                "league":     league,
                "league_url": league_url,
                "home_team":  home_team,
                "away_team":  away_team,
                "kickoff":    kickoff_iso,
                "status":     status,
                "minute":     minute,
                "score":      {"home": score_home, "away": score_away} if score_home is not None else None,
                "match_url":  f"{BASE_URL}/match/{match_id}/",
            })
        except Exception as e:
            log.debug(f"Row parse error: {e}")

    log.info(f"FlashScore: {len(matches)} aktivnih utakmica")
    return matches, league_urls


def _build_league_map(page) -> tuple[dict, dict]:
    """Gradi {match_id: league_name} i {league_name: league_url}."""
    league_map  = {}
    league_urls = {}
    current     = "Football"
    current_url = None

    for el in page.css('[class*="event__header"], [id^="g_1_"]'):
        cls = el.attrib.get("class") or ""
        eid = el.attrib.get("id") or ""

        if "event__header" in cls:
            link = el.css("a")
            if link:
                href = link[0].attrib.get("href", "")
                if href:
                    current_url = BASE_URL + href if not href.startswith("http") else href

            name_el = el.css('[class*="event__title"]')
            if name_el:
                current = (name_el[0].text or "Football").strip()
            else:
                t = (el.text or "Football").strip().split("\n")[0]
                current = t or "Football"

            league_urls[current] = current_url

        elif eid.startswith("g_1_"):
            league_map[eid.replace("g_1_", "")] = current

    return league_map, league_urls


# ─── TEAM: POSLEDNJIH 5 UTAKMICA SA is_home FLAGOM ────────────────────────────

def scrape_recent_matches(team_name: str, team_url: str, n: int = 5) -> list[dict]:
    """
    Poslednjih n utakmica tima (home + away zajedno), sa is_home flagom.
    Sve utakmice (liga, kup itd. — ali ne prijateljske).
    """
    page = _fetch(team_url.rstrip("/") + "/results/", timeout=45000)
    if page is None:
        return []

    results = []
    for row in page.css('[id^="g_1_"]'):
        if len(results) >= n:
            break
        try:
            home = _get_name(row, '[class*="event__homeParticipant"]')
            away = _get_name(row, '[class*="event__awayParticipant"]')
            if not home or not away:
                continue

            sh = _get_txt(row, '[class*="event__score--home"]')
            sa = _get_txt(row, '[class*="event__score--away"]')
            if not sh.isdigit() or not sa.isdigit():
                continue

            score_h, score_a = int(sh), int(sa)
            is_team_home = team_name.lower()[:6] in home.lower()
            is_team_away = team_name.lower()[:6] in away.lower()
            if not is_team_home and not is_team_away:
                continue

            if is_team_home:
                tg, og, opp, is_home = score_h, score_a, away, True
                result = "W" if score_h > score_a else ("D" if score_h == score_a else "L")
            else:
                tg, og, opp, is_home = score_a, score_h, home, False
                result = "W" if score_a > score_h else ("D" if score_a == score_h else "L")

            results.append({
                "opponent":          opp,
                "score":             f"{tg}-{og}",
                "result":            result,
                "goals_scored":      tg,
                "goals_conceded":    og,
                "is_home":           is_home,
                "btts":              tg > 0 and og > 0,
                "total_goals":       tg + og,
                "date":              _get_txt(row, '[class*="event__time"]'),
                "opponent_position": 0,  # popunjava aggregator iz standings
            })
        except Exception as e:
            log.debug(f"Recent match error: {e}")

    return results


# ─── STARI form scraper (za detaljan modal prikaz) ─────────────────────────────

def scrape_team_form(team_name: str, team_url: str, venue: str = "home") -> list[dict]:
    """Poslednjih 5 utakmica tima na jednom terenu (home/away), za modal prikaz."""
    page = _fetch(team_url.rstrip("/") + "/results/", timeout=45000)
    if page is None:
        return []

    results = []
    for row in page.css('[id^="g_1_"]'):
        if len(results) >= 5:
            break
        try:
            home = _get_name(row, '[class*="event__homeParticipant"]')
            away = _get_name(row, '[class*="event__awayParticipant"]')
            if not home or not away:
                continue

            sh = _get_txt(row, '[class*="event__score--home"]')
            sa = _get_txt(row, '[class*="event__score--away"]')
            if not sh.isdigit() or not sa.isdigit():
                continue

            score_h, score_a = int(sh), int(sa)
            is_team_home = team_name.lower()[:6] in home.lower()
            is_team_away = team_name.lower()[:6] in away.lower()

            if venue == "home" and not is_team_home: continue
            if venue == "away" and not is_team_away: continue
            if not is_team_home and not is_team_away: continue

            if is_team_home:
                tg, og, opp = score_h, score_a, away
                result = "W" if score_h > score_a else ("D" if score_h == score_a else "L")
            else:
                tg, og, opp = score_a, score_h, home
                result = "W" if score_a > score_h else ("D" if score_a == score_h else "L")

            results.append({
                "opponent":       opp,
                "score":          f"{tg}-{og}",
                "result":         result,
                "goals_scored":   tg,
                "goals_conceded": og,
                "is_home":        is_team_home,
                "btts":           tg > 0 and og > 0,
                "total_goals":    tg + og,
                "date":           _get_txt(row, '[class*="event__time"]'),
            })
        except Exception as e:
            log.debug(f"Form error: {e}")
    return results


# ─── STANDINGS ────────────────────────────────────────────────────────────────

def scrape_league_standings(league_url: str) -> dict:
    """
    Scrapin ligu tabelu. Vraća {tim_ime_lowercase: pozicija}.
    """
    if not league_url:
        return {}

    standings_url = league_url.rstrip("/") + "/standings/"
    page = _fetch(standings_url, timeout=40000)
    if page is None:
        return {}

    standings = {}

    # Probaj različite selektore za tabelu
    rows = page.css('[class*="tableRow"]:not([class*="--head"]):not([class*="thead"])')
    if not rows:
        rows = page.css('[class*="table__row"]:not([class*="--head"])')

    for i, row in enumerate(rows[:30]):
        try:
            # Pozicija
            pos_el  = row.css('[class*="tableCellRank"], [class*="table__cell--rank"]')
            pos     = i + 1
            if pos_el:
                pt = (pos_el[0].text or "").strip()
                if pt.isdigit():
                    pos = int(pt)

            # Naziv tima
            name_el = row.css('[class*="tableCellParticipant"], [class*="participant__name"], a[href*="/team/"]')
            if name_el:
                raw = (name_el[0].text or "").strip().lower()
                raw = " ".join(raw.split())
                if raw and len(raw) > 1:
                    standings[raw] = pos
        except Exception:
            continue

    log.info(f"Standings: {len(standings)} timova iz {standings_url}")
    return standings


# ─── ODDS ──────────────────────────────────────────────────────────────────────

def scrape_match_odds(match_url: str) -> dict:
    """
    Scrapin 1X2 kvote za utakmicu sa FlashScore-a.
    Vraća {'home': float, 'draw': float, 'away': float, 'market_label': str}.
    """
    odds_url = match_url.rstrip("/") + "/#/match-odds/1x2/0"
    page = _fetch(odds_url, timeout=35000)
    if page is None:
        return {}

    # Pokušaj da nađe odds elemente
    # FlashScore odds su u tabeli sa bookmakers i njihovim kvotama
    rows = page.css('[class*="oddsRow"], [class*="ui-table__row"], [class*="odds__row"]')

    for row in rows[:15]:
        try:
            cells = row.css('td, [class*="oddsCell"], [class*="odds__odd"], [class*="kefOdds"]')
            if len(cells) < 3:
                continue

            def _parse(el):
                t = (el.text or "").strip()
                try:
                    v = float(t)
                    return v if 1.01 < v < 50 else None
                except Exception:
                    return None

            h = _parse(cells[0])
            d = _parse(cells[1])
            a = _parse(cells[2])

            if h and d and a:
                return {"home": h, "draw": d, "away": a}
        except Exception:
            continue

    # Fallback: traži bilo koji element sa klasom koja sadrži odds vrednosti
    odd_els = page.css('[class*="oddsValueInner"], [class*="kefValue"], [class*="odd-value"]')
    vals = []
    for el in odd_els[:6]:
        try:
            v = float((el.text or "").strip())
            if 1.01 < v < 50:
                vals.append(v)
        except Exception:
            pass

    if len(vals) >= 3:
        return {"home": vals[0], "draw": vals[1], "away": vals[2]}

    return {}


# ─── MATCH DETAIL STATS ────────────────────────────────────────────────────────

def scrape_match_details(match_url: str) -> dict:
    page = _fetch(match_url + "#match-statistics-0", timeout=40000)
    if page is None:
        return {}

    stats = {}
    for stat_row in page.css('[class*="statRow"], [class*="statistic__row"]'):
        try:
            home_el = stat_row.css('[class*="homeValue"], [class*="home-value"]')
            away_el = stat_row.css('[class*="awayValue"], [class*="away-value"]')
            name_el = stat_row.css('[class*="statCategory"], [class*="categoryName"]')
            if not name_el:
                continue

            name = (name_el[0].text or "").lower().strip()
            hv   = (home_el[0].text or "0") if home_el else "0"
            av   = (away_el[0].text or "0") if away_el else "0"

            def num(s):
                try: return float(s.replace("%","").strip())
                except: return 0.0

            if "possession" in name: stats["possession"]       = {"home": num(hv), "away": num(av)}
            elif "on target" in name: stats["shots_on_target"] = {"home": int(num(hv)), "away": int(num(av))}
            elif "shot" in name:      stats.setdefault("shots_total", {"home": int(num(hv)), "away": int(num(av))})
            elif "corner" in name:    stats["corners"]         = {"home": int(num(hv)), "away": int(num(av))}
            elif "attack" in name:    stats["dangerous_attacks"]= {"home": int(num(hv)), "away": int(num(av))}
            elif "yellow" in name:    stats["yellow_cards"]    = {"home": int(num(hv)), "away": int(num(av))}
            elif "red" in name:       stats["red_cards"]       = {"home": int(num(hv)), "away": int(num(av))}
        except Exception:
            continue

    return {"stats": stats}


# ─── H2H ──────────────────────────────────────────────────────────────────────

def scrape_h2h(match_url: str) -> list[dict]:
    page = _fetch(match_url.rstrip("/") + "/#/h2h/overall", timeout=35000)
    if page is None:
        return []

    results = []
    for row in page.css('[id^="g_1_"]'):
        if len(results) >= 5:
            break
        try:
            home = _get_name(row, '[class*="event__homeParticipant"]')
            away = _get_name(row, '[class*="event__awayParticipant"]')
            sh   = _get_txt(row, '[class*="event__score--home"]')
            sa   = _get_txt(row, '[class*="event__score--away"]')
            if not sh.isdigit() or not sa.isdigit():
                continue
            sh, sa = int(sh), int(sa)
            results.append({"home_team": home, "away_team": away, "score_home": sh, "score_away": sa, "btts": sh > 0 and sa > 0, "total_goals": sh + sa})
        except Exception:
            continue
    return results
