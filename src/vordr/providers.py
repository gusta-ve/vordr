"""Shared types for the cloud provider API clients.

Each provider (``hetzner``, ``vultr``, …) has its own module with a
``fetch_servers(token, *, timeout)`` function returning ``{name: ServerBilling}``. The
**manual** value in config always wins over what comes from here — list prices may
differ from what your account actually pays.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


class ProviderError(RuntimeError):
    """Failure talking to a provider's API (invalid token, network, etc.)."""


@dataclass
class ServerBilling:
    """A server's billing data, from the provider's API."""

    name: str
    created: date | None = None
    cost_net: float | None = None
    cost_gross: float | None = None
    currency: str = "USD"


@dataclass
class AccountBilling:
    """The **account** balance/billing of a provider (not a specific server).

    ``balance`` follows Vultr's convention: **negative = credit in your favor**
    (e.g. a signup bonus). ``pending_charges`` is the usage already accrued this
    cycle, not yet deducted. Postpaid (card) providers may not expose a balance.
    """

    balance: float | None = None
    pending_charges: float | None = None
    currency: str = "USD"

    @property
    def credit(self) -> float | None:
        """Available credit (negative balance becomes positive). ``None`` if unknown."""
        if self.balance is None:
            return None
        return round(-self.balance, 2) if self.balance < 0 else 0.0

    @property
    def net_remaining(self) -> float | None:
        """Credit after subtracting this cycle's pending usage."""
        cr = self.credit
        if cr is None:
            return None
        return round(cr - (self.pending_charges or 0.0), 2)


def parse_api_date(raw: object) -> date | None:
    """Convert an ISO-8601 timestamp (with ``Z``) into a :class:`date`."""
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
