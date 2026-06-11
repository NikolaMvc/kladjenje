import json
import logging
import os
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

DISK_PATH = os.path.join(os.path.dirname(__file__), "..", "cache_data.json")
DISK_KEYS = {"upcoming", "live", "tipovi", "last_updated"}


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._load_from_disk()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.time() + ttl)
        if key in DISK_KEYS:
            self._save_to_disk()

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def _save_to_disk(self):
        try:
            data = {}
            for k in DISK_KEYS:
                entry = self._store.get(k)
                if entry is not None:
                    value, expires_at = entry
                    data[k] = {"value": value, "expires_at": expires_at}
            with open(DISK_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            log.warning(f"Cache disk write failed: {e}")

    def _load_from_disk(self):
        try:
            if not os.path.exists(DISK_PATH):
                return
            with open(DISK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            loaded = 0
            for k, entry in data.items():
                expires_at = entry.get("expires_at", 0)
                # Produžimo TTL na 4h pri učitavanju — podaci su stari ali bolje nego ništa
                ttl_left = max(expires_at - now, 0)
                if ttl_left < 14400:
                    ttl_left = 14400
                self._store[k] = (entry["value"], now + ttl_left)
                loaded += 1
            if loaded:
                log.info(f"Cache učitan sa diska ({loaded} ključeva) — podaci odmah dostupni")
        except Exception as e:
            log.warning(f"Cache disk read failed: {e}")


cache = TTLCache()
