"""Consulta de expiração de domínio via RDAP — público, sem credenciais.

RDAP é o sucessor estruturado do WHOIS: devolve JSON em vez de texto livre. Usamos
o bootstrap ``rdap.org``, que redireciona para o servidor autoritativo de cada TLD
(ex.: Verisign para ``.com``, Registro.br para ``.com.br``).

O resultado é cacheado em disco (``~/.cache/vordr/rdap.json``) porque a data de
expiração só muda quando você renova o domínio — não faz sentido bater na rede a
cada ``vordr cost``. Qualquer falha de rede degrada graciosamente: devolve o cache
vencido se houver, senão ``None``.
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
CACHE_TTL = 7 * 86400  # 7 dias — expiração muda só na renovação

# O cache em disco é compartilhado por consultas paralelas (uma por host). Sem
# um lock, dois threads fazem load→modifica→save concorrente e um clobbera o
# outro (ou corrompe o JSON). O lock serializa apenas o acesso ao arquivo — a
# rede continua em paralelo.
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
        pass  # cache é otimização; falhar ao gravar não pode derrubar o comando


def _parse_expiration(payload: dict) -> date | None:
    """Extrai a data do evento ``expiration`` de uma resposta RDAP."""
    for event in payload.get("events", []):
        if event.get("eventAction") == "expiration":
            raw = str(event.get("eventDate", "")).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(raw).date()
            except ValueError:
                return None
    return None


def _fetch(name: str, timeout: int) -> date | None:
    """Faz a requisição RDAP (segue o redirect do bootstrap) e parseia."""
    req = urllib.request.Request(
        RDAP_BOOTSTRAP + name,
        headers={"Accept": "application/rdap+json", "User-Agent": "vordr"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https fixo)
        payload = json.load(resp)
    return _parse_expiration(payload)


def domain_expiry(
    name: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    now: float | None = None,
) -> date | None:
    """Data de expiração de ``name``, do cache ou da rede. ``None`` se indisponível."""
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
        expires = _fetch(name, timeout)  # rede fora do lock
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        # rede caiu: reaproveita o cache vencido se houver
        if entry and entry.get("expires"):
            return date.fromisoformat(entry["expires"])
        return None

    if use_cache:
        with _CACHE_LOCK:
            # relê dentro do lock para mesclar gravações concorrentes (não clobberar)
            cache = _load_cache()
            cache[name] = {
                "expires": expires.isoformat() if expires else None,
                "fetched_at": now,
            }
            _save_cache(cache)
    return expires
