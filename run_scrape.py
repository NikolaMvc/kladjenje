#!/usr/bin/env python3
"""Standalone scraper — GitHub Actions svakih 5 min."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from backend.scraper.aggregator import get_all_matches
from backend.analyzer.claude_analyzer import analyze_upcoming, analyze_live

OUT = "frontend/data"


def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def _tip_won(market: str, score_h: int, score_a: int) -> bool:
    """Da li je tip pogodjen na osnovu konacnog rezultata."""
    m = market.lower()
    if "pobeda domaćina" in m or m == "1":
        return score_h > score_a
    if "pobeda gosta" in m or m == "2":
        return score_a > score_h
    if "remi" in m or m == "x":
        return score_h == score_a
    if "1x" in m:
        return score_h >= score_a
    if "x2" in m:
        return score_a >= score_h
    if "over 2.5" in m:
        return (score_h + score_a) > 2
    if "under 2.5" in m:
        return (score_h + score_a) <= 2
    if "btts" in m:
        return score_h > 0 and score_a > 0
    return False


def main():
    ts = datetime.now(timezone.utc).strftime("%H:%M")
    print(f"[{ts}] Scraping pokrenut...")

    all_matches = get_all_matches()
    if not all_matches:
        print("Nema utakmica — cuvam stare podatke.")
        sys.exit(0)

    upcoming = [m for m in all_matches if m["status"] == "upcoming"]
    live     = [m for m in all_matches if m["status"] == "live"]
    finished = [m for m in all_matches if m["status"] == "finished"]
    print(f"Pronadjeno: {len(upcoming)} predstojecih, {len(live)} uzivo, {len(finished)} zavrsenih")

    # ── Analiziraj predstojeće ─────────────────────────────────────────────────
    upcoming_result = []
    for m in upcoming[:40]:
        try:
            m["tip"] = analyze_upcoming(m)
        except Exception as e:
            print(f"  Analiza greska ({m.get('home_team')}): {e}")
            m["tip"] = None
        upcoming_result.append(m)

    # ── Analiziraj uživo ───────────────────────────────────────────────────────
    live_result = []
    for m in live[:30]:
        try:
            m["tip"] = analyze_live(m)
        except Exception:
            m["tip"] = None
        live_result.append(m)

    # ── Tipovi: top 10, bez duplikata ─────────────────────────────────────────
    seen_ids = set()
    tipovi_candidates = sorted(
        [m for m in upcoming_result if m.get("tip") and m["tip"].get("confidence", 0) > 0],
        key=lambda x: x["tip"].get("confidence", 0),
        reverse=True
    )
    tipovi = []
    for m in tipovi_candidates:
        if m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            tipovi.append(m)
        if len(tipovi) == 10:
            break

    # ── Završeno: cross-reference prethodnih tipova sa završenim utakmicom ─────
    prev_tipovi   = _load_json(f"{OUT}/tipovi.json", {}).get("matches", [])
    prev_zavrseno = _load_json(f"{OUT}/zavrseno.json", {}).get("matches", [])

    prev_tip_ids   = {m["id"]: m for m in prev_tipovi}
    done_ids       = {m["id"] for m in prev_zavrseno}
    finished_by_id = {m["id"]: m for m in finished}

    zavrseno = list(prev_zavrseno)
    for fid, fm in finished_by_id.items():
        if fid in prev_tip_ids and fid not in done_ids:
            original = prev_tip_ids[fid]
            tip      = original.get("tip") or {}
            market   = tip.get("market", "")
            sh = (fm.get("score") or {}).get("home", 0) or 0
            sa = (fm.get("score") or {}).get("away", 0) or 0
            won = _tip_won(market, sh, sa) if market and market != "N/A" else None
            zavrseno.insert(0, {
                **original,
                "final_score":  fm.get("score"),
                "tip_result":   "win" if won else ("loss" if won is False else "unknown"),
            })

    # Max 10 zavrsenih
    zavrseno = zavrseno[:10]

    # ── Sačuvaj sve ───────────────────────────────────────────────────────────
    os.makedirs(OUT, exist_ok=True)
    _save_json(f"{OUT}/upcoming.json", {"matches": upcoming_result, "last_updated": ts})
    _save_json(f"{OUT}/live.json",     {"matches": live_result,     "last_updated": ts})
    _save_json(f"{OUT}/tipovi.json",   {"matches": tipovi,          "last_updated": ts})
    _save_json(f"{OUT}/zavrseno.json", {"matches": zavrseno,        "last_updated": ts})

    print(f"Sacuvano: {len(upcoming_result)} predstojecih, {len(live_result)} uzivo, "
          f"{len(tipovi)} tipova, {len(zavrseno)} zavrsenih")


if __name__ == "__main__":
    main()
