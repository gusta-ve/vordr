"""Tipos compartilhados pelos clientes de API de provedores de nuvem.

Cada provedor (``hetzner``, ``vultr``, …) tem seu módulo com uma função
``fetch_servers(token, *, timeout)`` que devolve ``{nome: ServerBilling}``. O valor
**manual** no config sempre vence o que vem daqui — preços de lista podem diferir do
que a sua conta realmente paga.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


class ProviderError(RuntimeError):
    """Falha ao falar com a API de um provedor (token inválido, rede, etc.)."""


@dataclass
class ServerBilling:
    """Dados de cobrança de um servidor, vindos da API do provedor."""

    name: str
    created: date | None = None
    cost_net: float | None = None
    cost_gross: float | None = None
    currency: str = "USD"


def parse_api_date(raw: object) -> date | None:
    """Converte um timestamp ISO-8601 (com ``Z``) em :class:`date`."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def to_amount(value: object) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None
