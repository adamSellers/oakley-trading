from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Union

from .config import Config


class FileCache:
    """File-based JSON cache with TTL and stale fallback."""

    def __init__(self, namespace: str = "default"):
        Config.ensure_dirs()
        self.cache_dir = Config.cache_dir / namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("\\", "_").replace("=", "_")
        return self.cache_dir / f"{safe_key}.json"

    def get(self, key: str, ttl: Optional[int] = None) -> Optional[Union[dict, list]]:
        """Return cached value if within TTL, or stale value up to 24hr as fallback."""
        path = self._key_path(key)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        age = time.time() - data.get("_ts", 0)

        if ttl is not None and age <= ttl:
            return data.get("value")

        # Stale fallback
        if age <= Config.stale_cache_max_age:
            result = data.get("value")
            if isinstance(result, dict):
                result["_stale"] = True
            return result

        return None

    def set(self, key: str, value) -> None:
        path = self._key_path(key)
        payload = {"_ts": time.time(), "value": value}
        path.write_text(json.dumps(payload, default=str))

    def clear(self, key: Optional[str] = None) -> None:
        if key:
            path = self._key_path(key)
            path.unlink(missing_ok=True)
        else:
            for f in self.cache_dir.glob("*.json"):
                f.unlink(missing_ok=True)
