"""
Betting analyzer — weighted form scoring po uputstvu korisnika.
Boduje poslednjih 5 utakmica svakog tima na osnovu rezultata, terena i pozicije protivnika.
"""

import math
import logging

log = logging.getLogger(__name__)


# ─── POISSON HELPERS ───────────────────────────────────────────────────────────

def _poisson(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _over_prob(exp_total, threshold):
    return max(0.0, min(1.0, 1.0 - sum(_poisson(k, exp_total) for k in range(int(threshold) + 1))))


def _safe(d, key, default=1.2):
    val = (d or {}).get(key, default)
    return float(val) if val is not None else default


# ─── WEIGHTED SCORING SYSTEM (po uputstvu korisnika) ──────────────────────────

def _score_single(result: str, is_home: bool, opp_pos: int) -> int:
    """
    Bodovi za jednu utakmicu:
    Pobeda kod kuće vs 1-5  → 3  | vs 6+  → 2
    Pobeda u gostima vs 1-8 → 3  | vs 9+  → 2
    Nereš. kod kuće vs 1-8  → 1  | vs 9+  → 0
    Nereš. u gostima vs 1-2 → 2  | vs 3-14 → 1 | vs 15+ → 0
    Poraz kod kuće vs 1-2   → 1  | vs 3+  → 0
    Poraz u gostima vs 1-8  → 1  | vs 9+  → 0
    """
    if opp_pos <= 0:
        opp_pos = 10  # default mid-table

    if result == "W":
        if is_home:
            return 3 if opp_pos <= 5 else 2
        else:
            return 3 if opp_pos <= 8 else 2
    elif result == "D":
        if is_home:
            return 1 if opp_pos <= 8 else 0
        else:
            if opp_pos <= 2:  return 2
            elif opp_pos <= 14: return 1
            else: return 0
    else:  # L
        if is_home:
            return 1 if opp_pos <= 2 else 0
        else:
            return 1 if opp_pos <= 8 else 0


def _weighted_form(matches: list, standings: dict) -> tuple[float, list]:
    """
    Računa prosečan skor za poslednjih 5 utakmica po novom sistemu.
    Vraća (avg_score, breakdown_lista).
    """
    if not matches:
        return 1.0, []

    total = 0
    breakdown = []
    n = min(len(matches), 5)

    for m in matches[:5]:
        opponent   = m.get("opponent", "?")
        is_home    = m.get("is_home", True)
        result     = m.get("result", "L")

        # Pozicija protivnika iz standings tabele
        opp_pos = m.get("opponent_position", 0)
        if opp_pos <= 0:
            opp_lower = opponent.lower()
            opp_pos   = standings.get(opp_lower, 0)
            if opp_pos == 0:
                for k, v in standings.items():
                    if len(k) >= 4 and len(opp_lower) >= 4:
                        if k[:4] in opp_lower or opp_lower[:4] in k:
                            opp_pos = v
                            break
            if opp_pos == 0:
                opp_pos = 10

        pts = _score_single(result, is_home, opp_pos)
        total += pts

        ven  = "kod kuće" if is_home else "u gostima"
        res  = {"W": "Pobeda", "D": "Nerešeno", "L": "Poraz"}.get(result, result)
        breakdown.append({
            "opponent": opponent,
            "result": result,
            "is_home": is_home,
            "opp_pos": opp_pos,
            "pts": pts,
            "desc": f"{res} {ven} vs #{opp_pos} {opponent} = {pts}pt",
        })

    avg = round(total / n, 3)
    return avg, breakdown


# ─── UPCOMING ANALYSIS ─────────────────────────────────────────────────────────

def analyze_upcoming(match: dict) -> dict:
    home = match.get("home_team", "?")
    away = match.get("away_team", "?")

    standings   = match.get("standings") or {}
    home_recent = match.get("home_recent_5") or _fallback_recent(match, "home")
    away_recent = match.get("away_recent_5") or _fallback_recent(match, "away")

    home_avg, home_bd = _weighted_form(home_recent, standings)
    away_avg, away_bd = _weighted_form(away_recent, standings)

    diff     = home_avg - away_avg   # + = domaćin jači, - = gost jači
    abs_diff = abs(diff)

    # ── Tip: samo pobeda domaćina ili gosta ───────────────────────────────────
    if diff >= 0:
        market   = f"1 — Pobeda: {home}"
        odds_key = "home"
    else:
        market   = f"2 — Pobeda: {away}"
        odds_key = "away"

    # Confidence: 50% baza + razlika × faktor (max 90%)
    # diff=0 → 50%, diff=1.0 → 63%, diff=2.0 → 77%, diff=3.0 → 90%
    confidence = min(90, round(50 + abs_diff * 13.3))

    # Kvota za ovaj specifičan tip sa FlashScore
    odds     = match.get("odds") or {}
    tip_odds = odds.get(odds_key)

    stars = max(1, min(5, round(confidence / 20)))

    home_pts = sum(d["pts"] for d in home_bd)
    away_pts = sum(d["pts"] for d in away_bd)
    explanation = (
        f"{home}: {home_pts}pt / {len(home_bd)} utakmica = prosek {home_avg:.2f}. "
        f"{away}: {away_pts}pt / {len(away_bd)} utakmica = prosek {away_avg:.2f}. "
        f"{'Domaćin' if diff >= 0 else 'Gost'} je jači za {abs_diff:.2f} boda — "
        f"tip '{market}' sa {confidence}% sigurnosti."
    )

    key_factors = [d["desc"] for d in home_bd] + [d["desc"] for d in away_bd]

    return {
        "market":     market,
        "tip_odds":   tip_odds,
        "confidence": confidence,
        "stars":      stars,
        "explanation": explanation,
        "key_factors": key_factors[:10],
        "stats_breakdown": {
            "home_form_avg":  home_avg,
            "away_form_avg":  away_avg,
            "difference":     round(diff, 3),
            "home_breakdown": home_bd,
            "away_breakdown": away_bd,
        },
    }


def _fallback_recent(match: dict, side: str) -> list:
    """Ako nema home_recent_5, napravi listu iz postojećih summary podataka."""
    if side == "home":
        hfh = (match.get("home_form_home_summary") or {}).get("matches", [])
        hfa = (match.get("home_form_away_summary") or {}).get("matches", [])
        for m in hfh: m.setdefault("is_home", True)
        for m in hfa: m.setdefault("is_home", False)
        return (hfh + hfa)[:5]
    else:
        afh = (match.get("away_form_home_summary") or {}).get("matches", [])
        afa = (match.get("away_form_away_summary") or {}).get("matches", [])
        for m in afh: m.setdefault("is_home", True)
        for m in afa: m.setdefault("is_home", False)
        return (afh + afa)[:5]


# ─── LIVE ANALYSIS ─────────────────────────────────────────────────────────────

def analyze_live(match: dict) -> dict:
    home  = match.get("home_team", "?")
    away  = match.get("away_team", "?")
    stats = match.get("stats") or {}
    score = match.get("score") or {}
    minute = match.get("minute") or 45

    score_h   = score.get("home") or 0
    score_a   = score.get("away") or 0
    remaining = max(0, 90 - minute)

    def _st(stat, side, default=0):
        return (stats.get(stat) or {}).get(side, default)

    xg_h        = _st("xg", "home", 0.0)
    xg_a        = _st("xg", "away", 0.0)
    poss_h      = _st("possession", "home", 50)
    shots_on_h  = _st("shots_on_target", "home", 0)
    shots_on_a  = _st("shots_on_target", "away", 0)
    dangerous_h = _st("dangerous_attacks", "home", 0)
    dangerous_a = _st("dangerous_attacks", "away", 0)
    red_h       = _st("red_cards", "home", 0)
    red_a       = _st("red_cards", "away", 0)

    # Momentum
    def _ratio(a, b):
        return a / (a + b) if (a + b) > 0 else 0.5

    m_h = (
        _ratio(shots_on_h, shots_on_a) * 0.35 +
        (poss_h / 100)                          * 0.20 +
        _ratio(dangerous_h, dangerous_a)        * 0.25 +
        _ratio(xg_h, xg_a)                     * 0.20
    )
    m_a = 1 - m_h
    if red_h > 0: m_h *= 0.75 ** red_h
    if red_a > 0: m_a *= 0.75 ** red_a
    norm = m_h + m_a
    m_h, m_a = m_h / norm, m_a / norm

    rate = ((xg_h + xg_a) / max(minute, 1)) if (xg_h + xg_a) > 0 else (2.5 / 90)
    exp_r   = rate * remaining
    exp_r_h = exp_r * m_h
    exp_r_a = exp_r * m_a

    from math import factorial, exp
    def _pmf(k, lam):
        return exp(-lam) * (lam ** k) / factorial(k) if lam > 0 else (1 if k == 0 else 0)

    def _1x2(lh, la):
        hw = dr = aw = 0.0
        for i in range(9):
            for j in range(9):
                p = _pmf(i, lh) * _pmf(j, la)
                if i > j: hw += p
                elif i == j: dr += p
                else: aw += p
        return hw, dr, aw

    p1, px, p2 = _1x2(exp_r_h + 0.01, exp_r_a + 0.01)
    if score_h > score_a:
        p1 = min(p1 * 1.3, 0.93)
    elif score_a > score_h:
        p2 = min(p2 * 1.3, 0.93)
    t = p1 + px + p2
    p1, px, p2 = p1/t, px/t, p2/t

    n_t   = score_h + score_a
    o_nxt = _over_prob(exp_r, 0.5)

    markets = {
        f"Domaćin pobeđuje [{score_h}-{score_a}]": round(p1 * 100),
        f"Remi [{score_h}-{score_a}]":             round(px * 100),
        f"Gost pobeđuje [{score_h}-{score_a}]":    round(p2 * 100),
        f"Over {n_t + 0.5} golova":                round(min(o_nxt * 100, 92)),
    }

    best_market = max(markets, key=lambda k: markets[k])
    confidence  = markets[best_market]
    stars       = max(1, min(5, round(confidence / 20)))

    dominant = home if m_h > m_a else away
    explanation = (
        f"Rezultat {score_h}-{score_a} u {minute}'. min, ostalo {remaining} min. "
        f"{dominant} dominira — posedovanje {round(poss_h if dominant==home else 100-poss_h)}%, "
        f"šutevi na gol {shots_on_h if dominant==home else shots_on_a}. "
        f"xG: {xg_h:.2f}-{xg_a:.2f}. "
        f"Momentum: {home} {round(m_h*100)}% / {away} {round(m_a*100)}%."
    )

    return {
        "market":     best_market,
        "confidence": confidence,
        "stars":      stars,
        "explanation": explanation,
        "key_factors": [
            f"xG: {home} {xg_h:.2f} — {away} {xg_a:.2f}",
            f"Posedovanje: {poss_h}% — {100-poss_h}%",
            f"Šutevi na gol: {shots_on_h} — {shots_on_a}",
            f"Momentum: {home} {round(m_h*100)}% / {away} {round(m_a*100)}%",
            f"Preostalo: {remaining} min",
        ],
        "stats_breakdown": {
            "momentum_home": round(m_h, 2),
            "momentum_away": round(m_a, 2),
            "xg_home": xg_h,
            "xg_away": xg_a,
            "all_markets": markets,
        },
    }


