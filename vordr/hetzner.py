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

from .providers import ProviderError, ServerBilling, parse_api_date, to_amount

API_URL = "https://api.hetzner.cloud/v1/servers"
DEFAULT_TIMEOUT = 15

# A Hetzner cobra no cartão, postpago (dia 1º do mês seguinte). A Cloud API NÃO
# expõe saldo nem fatura — isso vive só no console web — então não há fetch_account:
# a cobrança é tratada por calendário (próximo dia 1º) + custo estimado.
BILLING_MODEL = "postpaid"


class HetznerError(ProviderError):
    """Falha ao falar com a API da Hetzner (token inválido, rede, etc.)."""


def _monthly_price(server: dict) -> tuple[float | None, float | None]:
    """Preço mensal (net, gross) do tipo do servidor, na localização dele."""
    st = server.get("server_type") or {}
    loc = (server.get("datacenter") or {}).get("location", {}).get("name")
    prices = st.get("prices") or []
    chosen = next((p for p in prices if p.get("location") == loc), None)
    if chosen is None and prices:
        chosen = prices[0]
    pm = (chosen or {}).get("price_monthly", {})
    return to_amount(pm.get("net")), to_amount(pm.get("gross"))


def parse_servers(payload: dict) -> dict[str, ServerBilling]:
    result: dict[str, ServerBilling] = {}
    for server in payload.get("servers", []):
        name = server.get("name")
        if not name:
            continue
        net, gross = _monthly_price(server)
        result[name] = ServerBilling(
            name=name,
            created=parse_api_date(server.get("created")),
            cost_net=net,
            cost_gross=gross,
            currency="EUR",  # Hetzner fatura em EUR
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
