"""Enkel disk-cache for HTTP-kall. Alt rått lagres under pipeline/cache/ (ikke i git)."""
import hashlib
import json
import time
from pathlib import Path

import requests

from .paths import CACHE_DIR

USER_AGENT = "gulloye-pipeline/0.1 (https://github.com/Snkpipefish/gulloye)"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _key(url: str, params=None, data=None) -> str:
    raw = json.dumps([url, params, data], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cached_get(url: str, params: dict | None = None, *, suffix: str = ".bin",
               data: dict | None = None, timeout: int = 180, retries: int = 3,
               subdir: str = "http", min_bytes: int = 1) -> Path:
    """GET (eller POST når data er satt). Returnerer sti til cachet fil."""
    d = CACHE_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    path = d / (_key(url, params, data) + suffix)
    if path.exists() and path.stat().st_size >= min_bytes:
        return path
    missing = path.with_suffix(path.suffix + ".404")
    if missing.exists():
        raise RuntimeError(f"{url}: HTTP 404 (cachet)")
    last = None
    for attempt in range(retries):
        try:
            if data is not None:
                r = _session.post(url, data=data, params=params, timeout=timeout)
            else:
                r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200 and len(r.content) >= min_bytes:
                path.write_bytes(r.content)
                return path
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (403, 404):
                missing.write_text(last)
                break
        except requests.RequestException as e:  # noqa: PERF203
            last = repr(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Klarte ikke hente {url} ({last})")


def cached_json(url: str, params: dict | None = None, **kw):
    p = cached_get(url, params, suffix=".json", **kw)
    return json.loads(p.read_text(encoding="utf-8"))


def cached_text(url: str, params: dict | None = None, **kw) -> str:
    p = cached_get(url, params, suffix=".txt", **kw)
    return p.read_text(encoding="utf-8", errors="replace")
