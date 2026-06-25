"""Minimal Vultr v2 API client — read-only.

Pulls each instance's creation date (``date_created`` → ``since``) and the plan's
monthly cost. As with Hetzner, the price is the **plan list price** (Vultr doesn't
expose the exact per-instance value, including region surcharges such as São Paulo);
that's why the manual value in config always wins.

Note: the Vultr token is *full-access* (there's no read-only option) and the API uses
an IP allowlist — add your IP under Account → API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .providers import AccountBilling, ProviderError, ServerBilling, parse_api_date, to_amount

INSTANCES_URL = "https://api.vultr.com/v2/instances?per_page=500"
PLANS_URL = "https://api.vultr.com/v2/plans?per_page=500"
ACCOUNT_URL = "https://api.vultr.com/v2/account"
DEFAULT_TIMEOUT = 15

# Vultr is prepaid: usage is drawn from a balance/credit (e.g. a signup bonus).
BILLING_MODEL = "prepaid"


class VultrError(ProviderError):
    """Failure talking to the Vultr API (invalid token, IP not allowed, etc.)."""


def _get(url: str, token: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "vordr"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https)
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise VultrError(
                f"invalid token or IP not allowed (HTTP {exc.code}) — "
                "check the allowlist under Account → API"
            ) from exc
        raise VultrError(f"HTTP {exc.code} from the Vultr API") from exc
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise VultrError(f"failed to contact the Vultr API: {exc}") from exc


def _plan_costs(token: str, timeout: int) -> dict[str, float]:
    costs: dict[str, float] = {}
    for plan in _get(PLANS_URL, token, timeout).get("plans", []):
        amount = to_amount(plan.get("monthly_cost"))
        if plan.get("id") and amount is not None:
            costs[plan["id"]] = amount
    return costs


def parse_instances(payload: dict, plan_costs: dict[str, float]) -> dict[str, ServerBilling]:
    result: dict[str, ServerBilling] = {}
    for inst in payload.get("instances", []):
        name = inst.get("label") or inst.get("id")
        if not name:
            continue
        cost = plan_costs.get(inst.get("plan"))
        result[name] = ServerBilling(
            name=name,
            created=parse_api_date(inst.get("date_created")),
            cost_net=cost,
            cost_gross=cost,  # Vultr doesn't distinguish net/gross
            currency="USD",
        )
    return result


def fetch_servers(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, ServerBilling]:
    """List the account's instances. Raises :class:`VultrError` on failure."""
    plan_costs = _plan_costs(token, timeout)
    instances = _get(INSTANCES_URL, token, timeout)
    return parse_instances(instances, plan_costs)


def parse_account(payload: dict) -> AccountBilling:
    acc = payload.get("account", payload)
    return AccountBilling(
        balance=to_amount(acc.get("balance")),
        pending_charges=to_amount(acc.get("pending_charges")),
        currency="USD",
    )


def fetch_account(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> AccountBilling:
    """Account balance and pending charges. Raises :class:`VultrError` on failure."""
    return parse_account(_get(ACCOUNT_URL, token, timeout))
