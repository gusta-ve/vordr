"""Minimal Hetzner Cloud API client — read-only.

Pulls each server's creation date (``created`` → ``since``) and the type's monthly
price. Note: the API price is the **current list price of the server type**, not
necessarily what your account pays (promo or legacy prices are locked to the account).
That's why the manual value in config always wins.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .providers import ProviderError, ServerBilling, parse_api_date, to_amount

API_URL = "https://api.hetzner.cloud/v1/servers"
DEFAULT_TIMEOUT = 15

# Hetzner charges to the card, postpaid (1st of the next month). The Cloud API does
# NOT expose a balance or invoice — that lives only in the web console — so there's no
# fetch_account: billing is handled by calendar (next 1st) + estimated cost.
BILLING_MODEL = "postpaid"


class HetznerError(ProviderError):
    """Failure talking to the Hetzner API (invalid token, network, etc.)."""


def _monthly_price(server: dict) -> tuple[float | None, float | None]:
    """Monthly price (net, gross) of the server's type, at its location."""
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
            currency="EUR",  # Hetzner bills in EUR
        )
    return result


def fetch_servers(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, ServerBilling]:
    """List the account's servers. Raises :class:`HetznerError` on failure."""
    req = urllib.request.Request(
        API_URL,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "vordr"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https)
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HetznerError("invalid token or no permission (HTTP 401)") from exc
        raise HetznerError(f"HTTP {exc.code} from the Hetzner API") from exc
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HetznerError(f"failed to contact the Hetzner API: {exc}") from exc
    return parse_servers(payload)
