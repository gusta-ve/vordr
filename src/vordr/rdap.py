"""Domain expiry lookup via RDAP — public, no credentials.

RDAP is the structured successor to WHOIS: it returns JSON instead of free text. We
use the ``rdap.org`` bootstrap, which redirects to each TLD's authoritative server
(e.g. Verisign for ``.com``, Registro.br for ``.com.br``).

The result is cached on disk (``~/.cache/vordr/rdap.json``) because the expiry date
only changes when you renew the domain — no point hitting the network on every
``vordr cost``. Any network failure degrades gracefully: it returns the stale cache
if any, otherwise ``None``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

RDAP_BOOTSTRAP = "https://rdap.org/domain/"
DEFAULT_TIMEOUT = 10
CACHE_TTL = 7 * 86400  # 7 days — expiry only changes on renewal

# The disk cache is shared by parallel lookups (one per host). Without a lock, two
# threads do a concurrent load→modify→save and one clobbers the other (or corrupts
# the JSON). The lock serializes only the file access — the network stays parallel.
_CACHE_LOCK = threading.Lock()


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", "~/.cache")
    return Path(base).expanduser() / "vordr" / "rdap.json"


def _load_cache() -> dict:
    try:
        with _cache_path().open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass  # the cache is an optimization; a write failure must not break the command


def _parse_expiration(payload: dict) -> date | None:
    """Extract the ``expiration`` event date from an RDAP response."""
    for event in payload.get("events", []):
        if event.get("eventAction") == "expiration":
            raw = str(event.get("eventDate", "")).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(raw).date()
            except ValueError:
                return None
    return None


def _fetch(name: str, timeout: int) -> date | None:
    """Make the RDAP request (follows the bootstrap redirect) and parse it."""
    req = urllib.request.Request(
        RDAP_BOOTSTRAP + name,
        headers={"Accept": "application/rdap+json", "User-Agent": "vordr"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https)
        payload = json.load(resp)
    return _parse_expiration(payload)


def domain_expiry(
    name: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    now: float | None = None,
) -> date | None:
    """Expiry date of ``name``, from cache or network. ``None`` if unavailable."""
    name = name.strip().lower()
    if not name:
        return None

    now = time.time() if now is None else now
    if use_cache:
        with _CACHE_LOCK:
            entry = _load_cache().get(name)
    else:
        entry = None
    if entry and now - entry.get("fetched_at", 0) < CACHE_TTL:
        iso = entry.get("expires")
        return date.fromisoformat(iso) if iso else None

    try:
        expires = _fetch(name, timeout)  # network outside the lock
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        # network down: reuse the stale cache if any
        if entry and entry.get("expires"):
            return date.fromisoformat(entry["expires"])
        return None

    if use_cache:
        with _CACHE_LOCK:
            # re-read inside the lock to merge concurrent writes (don't clobber)
            cache = _load_cache()
            cache[name] = {
                "expires": expires.isoformat() if expires else None,
                "fetched_at": now,
            }
            _save_cache(cache)
    return expires
