"""
BetAdvisor FastAPI — pozadinski scraper + instant cache serving.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("betadvisor")

from .cache import cache
from .scraper.aggregator import get_all_matches, enrich_for_analysis, enrich_match
from .analyzer.claude_analyzer import analyze_upcoming, analyze_live

app = FastAPI(title="BetAdvisor", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

_executor     = ThreadPoolExecutor(max_workers=4)
_scrape_lock  = asyncio.Lock()
_is_scraping  = False


# ─── BACKGROUND SCRAPER ────────────────────────────────────────────────────────

async def _do_scrape(loop):
    global _is_scraping
    async with _scrape_lock:
        _is_scraping = True
    try:
        log.info("Scraping pokrenut...")
        matches = await loop.run_in_executor(_executor, get_all_matches)
        if not matches:
            cache.set("last_error", "Nema utakmica", ttl=120)
            return

        upcoming = [m for m in matches if m["status"] == "upcoming"]
        live     = [m for m in matches if m["status"] == "live"]
        log.info(f"Pronađeno: {len(upcoming)} predstojecih, {len(live)} uzivo")

        # ── FAZA 1: brza analiza bez enrichmenta → odmah u keš ──────────────
        upcoming_result = []
        for m in upcoming[:40]:
            try:
                tip = await loop.run_in_executor(_executor, analyze_upcoming, m)
                m["tip"] = tip
            except Exception:
                m["tip"] = None
            upcoming_result.append(m)

        live_result = []
        for m in live[:30]:
            try:
                tip = await loop.run_in_executor(_executor, analyze_live, m)
                m["tip"] = tip
            except Exception:
                m["tip"] = None
            live_result.append(m)

        _save_to_cache(upcoming_result, live_result)
        log.info("Faza 1 gotova — podaci odmah dostupni u frontendu")

        # ── FAZA 2: enrich top 10 predstojecih sa odds/standings u pozadini ─
        top10 = sorted(
            [m for m in upcoming_result if m.get("tip")],
            key=lambda x: x["tip"].get("confidence", 0),
            reverse=True
        )[:10]

        for m in top10:
            try:
                enriched = await loop.run_in_executor(_executor, enrich_for_analysis, m)
                tip = await loop.run_in_executor(_executor, analyze_upcoming, enriched)
                enriched["tip"] = tip
                # Zameni stari red novim enrichovanim
                for i, um in enumerate(upcoming_result):
                    if um["id"] == enriched["id"]:
                        upcoming_result[i] = enriched
                        break
            except Exception as e:
                log.debug(f"Enrich greška {m.get('id')}: {e}")

        _save_to_cache(upcoming_result, live_result)
        log.info("Faza 2 gotova — top 10 utakmica enrichovano")

    except Exception as e:
        log.error(f"Scrape greška: {e}", exc_info=True)
        cache.set("last_error", str(e), ttl=120)
    finally:
        async with _scrape_lock:
            _is_scraping = False


def _save_to_cache(upcoming_result, live_result):
    all_with_tips = [m for m in upcoming_result + live_result if m.get("tip")]
    tipovi = sorted(
        all_with_tips,
        key=lambda x: x["tip"].get("confidence", 0),
        reverse=True
    )[:20]
    cache.set("upcoming",     upcoming_result, ttl=300)
    cache.set("live",         live_result,     ttl=300)
    cache.set("tipovi",       tipovi,          ttl=300)
    cache.set("last_updated", _now_str(),      ttl=600)
    cache.set("last_error",   None,            ttl=600)


async def _background_scrape():
    loop = asyncio.get_event_loop()
    while True:
        await _do_scrape(loop)
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_background_scrape())
    log.info("Background scraper pokrenut. Podaci dostupni za ~30s.")


# ─── API ───────────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/api/upcoming")
async def get_upcoming():
    data = cache.get("upcoming") or []
    # Filter: samo status == upcoming
    data = [m for m in data if m.get("status") == "upcoming"]
    return {
        "matches":      data,
        "last_updated": cache.get("last_updated"),
        "is_loading":   _is_scraping and len(data) == 0,
        "error":        cache.get("last_error"),
    }


@app.get("/api/live")
async def get_live():
    data = cache.get("live") or []
    # Filter: samo status == live
    data = [m for m in data if m.get("status") == "live"]
    return {
        "matches":      data,
        "last_updated": cache.get("last_updated"),
        "is_loading":   _is_scraping and len(data) == 0,
        "error":        cache.get("last_error"),
    }


@app.get("/api/tipovi")
async def get_tipovi():
    """Top 20 najsigurnijih tipova, sortirano po confidence %."""
    data = cache.get("tipovi") or []
    return {
        "matches":      data,
        "last_updated": cache.get("last_updated"),
        "is_loading":   _is_scraping and len(data) == 0,
        "error":        cache.get("last_error"),
    }


@app.get("/api/status")
async def get_status():
    return {
        "is_scraping":    _is_scraping,
        "last_updated":   cache.get("last_updated"),
        "upcoming_count": len(cache.get("upcoming") or []),
        "live_count":     len(cache.get("live") or []),
        "error":          cache.get("last_error"),
    }


@app.get("/api/match/{match_id}")
async def get_match_detail(match_id: str):
    cache_key = f"detail_{match_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    all_matches = (cache.get("upcoming") or []) + (cache.get("live") or [])
    match = next((m for m in all_matches if m.get("id") == match_id), None)
    if not match:
        return {"error": "Utakmica nije pronađena. Osvežite listu."}

    loop = asyncio.get_event_loop()

    try:
        enriched = await loop.run_in_executor(_executor, enrich_match, match)
    except Exception as e:
        log.warning(f"Enrich greška {match_id}: {e}")
        enriched = dict(match)

    try:
        from .analyzer.news import search_match_news, extract_injury_summary
        news_items = await loop.run_in_executor(
            _executor, search_match_news,
            match["home_team"], match["away_team"], match.get("league", "")
        )
        enriched["news"] = extract_injury_summary(news_items, match["home_team"], match["away_team"])
    except Exception:
        enriched["news"] = {"home_missing": [], "away_missing": [], "notes": []}

    try:
        fn = analyze_live if enriched.get("status") == "live" else analyze_upcoming
        enriched["tip"] = await loop.run_in_executor(_executor, fn, enriched)
    except Exception as e:
        log.warning(f"Analiza greška: {e}")

    result = {k: v for k, v in enriched.items() if k not in {"match_details", "sofa_stats", "ls_stats"}}
    cache.set(cache_key, result, ttl=300)
    return result


@app.post("/api/refresh")
async def force_refresh():
    cache.delete("upcoming")
    cache.delete("live")
    cache.delete("tipovi")
    cache.delete("last_updated")
    asyncio.create_task(_do_scrape(asyncio.get_event_loop()))
    return {"status": "ok", "message": "Osvežavanje pokrenuto."}


def _now_str():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
