#!/usr/bin/env python3
"""Standalone scraper — pokrece GitHub Actions svakih 5 min, cuva JSON u data/."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from backend.scraper.aggregator import get_all_matches
from backend.analyzer.claude_analyzer import analyze_upcoming, analyze_live


def main():
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Scraping pokrenut...")

    matches = get_all_matches()
    if not matches:
        print("Nema utakmica — cuvam stare podatke.")
        sys.exit(0)

    upcoming = [m for m in matches if m["status"] == "upcoming"]
    live     = [m for m in matches if m["status"] == "live"]
    print(f"Pronadjeno: {len(upcoming)} predstojecih, {len(live)} uzivo")

    upcoming_result = []
    for m in upcoming[:40]:
        try:
            m["tip"] = analyze_upcoming(m)
        except Exception as e:
            print(f"  Analiza greska ({m.get('home_team')}): {e}")
            m["tip"] = None
        upcoming_result.append(m)

    live_result = []
    for m in live[:30]:
        try:
            m["tip"] = analyze_live(m)
        except Exception as e:
            m["tip"] = None
        live_result.append(m)

    tipovi = sorted(
        [m for m in upcoming_result if m.get("tip")],
        key=lambda x: x["tip"].get("confidence", 0),
        reverse=True
    )[:20]

    ts = datetime.now(timezone.utc).strftime("%H:%M")
    os.makedirs("data", exist_ok=True)

    files = {
        "upcoming.json": {"matches": upcoming_result, "last_updated": ts},
        "live.json":     {"matches": live_result,     "last_updated": ts},
        "tipovi.json":   {"matches": tipovi,           "last_updated": ts},
    }
    for fname, payload in files.items():
        with open(f"data/{fname}", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  Sacuvano: data/{fname}")

    print(f"Gotovo — {len(upcoming_result)} predstojecih, {len(live_result)} uzivo, {len(tipovi)} tipova")


if __name__ == "__main__":
    main()
