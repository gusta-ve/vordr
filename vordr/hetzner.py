"""Cliente mínimo da API Hetzner Cloud — somente leitura.

Puxa a data de criação de cada servidor (``created`` → ``since``) e o preço
mensal do tipo. Atenção: o preço da API é o **preço de lista atual do tipo de
servidor**, não necessariamente o que a sua conta paga (preços promocionais ou
legados ficam travados na conta). Por isso o valor manual no config sempre vence.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

API_URL = "https://api.hetzner.cloud/v1/servers"
DEFAULT_TIMEOUT = 15


class HetznerError(RuntimeError):
    """Falha ao falar com a API da Hetzner (token inválido, rede, etc.)."""


@dataclass
class ServerBilling:
    """Dados de cobrança de um servidor, vindos da API."""

    name: str
    created: date | None = None
    cost_net: float | None = None
    cost_gross: float | None = None
    currency: str = "EUR"  # Hetzner fatura em EUR


def _parse_created(raw: object) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _monthly_price(server: dict) -> tuple[float | None, float | None]:
    """Preço mensal (net, gross) do tipo do servidor, na localização dele."""
    st = server.get("server_type") or {}
    loc = (server.get("datacenter") or {}).get("location", {}).get("name")
    prices = st.get("prices") or []
    chosen = next((p for p in prices if p.get("location") == loc), None)
    if chosen is None and prices:
        chosen = prices[0]
    pm = (chosen or {}).get("price_monthly", {})

    def _num(value: object) -> float | None:
        try:
            return round(float(value), 2) if value is not None else None
        except (TypeError, ValueError):
            return None

    return _num(pm.get("net")), _num(pm.get("gross"))


def parse_servers(payload: dict) -> dict[str, ServerBilling]:
    result: dict[str, ServerBilling] = {}
    for server in payload.get("servers", []):
        name = server.get("name")
        if not name:
            continue
        net, gross = _monthly_price(server)
        result[name] = ServerBilling(
            name=name,
            created=_parse_created(server.get("created")),
            cost_net=net,
            cost_gross=gross,
        )
    return result


def fetch_servers(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, ServerBilling]:
    """Lista os servidores da conta. Levanta :class:`HetznerError` em falha."""
    req = urllib.request.Request(
        API_URL,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "vordr"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https fixo)
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HetznerError("token inválido ou sem permissão (HTTP 401)") from exc
        raise HetznerError(f"HTTP {exc.code} da API da Hetzner") from exc
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HetznerError(f"falha ao contatar a API da Hetzner: {exc}") from exc
    return parse_servers(payload)
