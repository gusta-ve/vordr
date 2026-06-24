"""Cliente mínimo da API Vultr v2 — somente leitura.

Puxa a data de criação de cada instância (``date_created`` → ``since``) e o custo
mensal do plano. Como na Hetzner, o preço é o **de lista do plano** (a Vultr não
expõe o valor exato por instância, incluindo sobretaxas de região como São Paulo);
por isso o valor manual no config sempre vence.

Atenção: o token da Vultr é *full-access* (não há opção read-only) e a API usa uma
allowlist de IP — adicione seu IP em Account → API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .providers import ProviderError, ServerBilling, parse_api_date, to_amount

INSTANCES_URL = "https://api.vultr.com/v2/instances?per_page=500"
PLANS_URL = "https://api.vultr.com/v2/plans?per_page=500"
DEFAULT_TIMEOUT = 15


class VultrError(ProviderError):
    """Falha ao falar com a API da Vultr (token inválido, IP não autorizado, etc.)."""


def _get(url: str, token: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "vordr"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https fixo)
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise VultrError(
                f"token inválido ou IP não autorizado (HTTP {exc.code}) — "
                "confira a allowlist em Account → API"
            ) from exc
        raise VultrError(f"HTTP {exc.code} da API da Vultr") from exc
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise VultrError(f"falha ao contatar a API da Vultr: {exc}") from exc


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
            cost_gross=cost,  # Vultr não distingue net/gross
            currency="USD",
        )
    return result


def fetch_servers(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, ServerBilling]:
    """Lista as instâncias da conta. Levanta :class:`VultrError` em falha."""
    plan_costs = _plan_costs(token, timeout)
    instances = _get(INSTANCES_URL, token, timeout)
    return parse_instances(instances, plan_costs)
