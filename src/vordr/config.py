"""Vordr configuration.

The configuration lives in ``~/.config/vordr/config.toml`` (or ``$VORDR_CONFIG``).
You describe which hosts to watch; run ``vordr init`` to generate a commented
example. With no hosts configured there is nothing to watch.

No IPs or secrets here: hosts are just *aliases* from your SSH config. Billing/expiry
dates are supplied by you — the server has no way to know when a provider will charge
again.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


class ConfigError(RuntimeError):
    """Invalid or malformed configuration."""


@dataclass
class Subscription:
    """A subscription with a renewal/expiry (server or domain).

    Fields are filled in by you in ``config.toml`` — the server has no way to know
    when the provider or registrar will charge again.
    """

    expires: date | None = None
    cost: float | None = None
    currency: str = "USD"
    cycle: str = "monthly"  # monthly | yearly
    provider: str | None = None  # provider (server) or registrar (domain)
    provider_ref: str | None = None  # server name/id in the provider's API
    name: str | None = None  # domain name (only meaningful for the domain)
    since: date | None = None  # since when you've kept it (hosting age)

    def days_left(self, today: date | None = None) -> int | None:
        if self.expires is None:
            return None
        today = today or date.today()
        return (self.expires - today).days

    def age_days(self, today: date | None = None) -> int | None:
        """Days elapsed since ``since`` (e.g. hosting age)."""
        if self.since is None:
            return None
        today = today or date.today()
        return (today - self.since).days

    @property
    def monthly_cost(self) -> float | None:
        if self.cost is None:
            return None
        if self.cycle == "yearly":
            return round(self.cost / 12, 2)
        return self.cost

    @property
    def has_data(self) -> bool:
        return self.expires is not None or self.cost is not None


@dataclass
class Host:
    """A server watched by Vordr."""

    name: str
    ssh: str
    label: str | None = None
    status_command: str | None = None
    server: Subscription = field(default_factory=Subscription)
    domain: Subscription | None = None

    @property
    def display(self) -> str:
        return self.label or self.name


@dataclass
class Config:
    hosts: dict[str, Host]
    warn_days: int = 14
    critical_days: int = 7
    # `vordr check` alert thresholds
    runway_days: int = 14     # warn when prepaid credit runs out within N days
    charge_days: int = 7      # warn when a charge/renewal/expiry is within N days
    ntfy: str | None = None   # ntfy URL/topic for `vordr check --notify`
    telegram_chat: str | None = None   # Telegram chat id (token lives in secrets)
    source: Path | None = None

    def host(self, name: str) -> Host:
        try:
            return self.hosts[name]
        except KeyError:
            known = ", ".join(self.hosts) or "(none)"
            raise ConfigError(f"host '{name}' not configured. Known: {known}") from None


# --- paths -----------------------------------------------------------------

def config_path() -> Path:
    env = os.environ.get("VORDR_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "vordr" / "config.toml"


# --- parsing ---------------------------------------------------------------

def _parse_date(value: object, ctx: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            raise ConfigError(f"{ctx}: invalid date '{value}' (use YYYY-MM-DD)") from None
    raise ConfigError(f"{ctx}: invalid date '{value!r}'")


def _parse_subscription(raw: dict, ctx: str, *, is_domain: bool = False) -> Subscription:
    if not isinstance(raw, dict):
        raise ConfigError(f"{ctx} must be a table")
    return Subscription(
        expires=_parse_date(raw.get("expires"), f"{ctx}.expires"),
        cost=raw.get("cost"),
        currency=raw.get("currency", "USD"),
        cycle=raw.get("cycle", "monthly"),
        # the domain uses "registrar"; the server uses "provider".
        provider=raw.get("registrar") if is_domain else raw.get("provider"),
        provider_ref=None if is_domain else raw.get("provider_server"),
        name=raw.get("name") if is_domain else None,
        since=None if is_domain else _parse_date(raw.get("since"), f"{ctx}.since"),
    )


def _parse_host(name: str, raw: dict) -> Host:
    if not isinstance(raw, dict):
        raise ConfigError(f"host '{name}' must be a table [hosts.{name}]")
    ssh_alias = raw.get("ssh", name)
    # [hosts.X.server] is the current name; we accept [hosts.X.billing] for compat.
    server_raw = raw.get("server", raw.get("billing", {}))
    domain_raw = raw.get("domain")
    return Host(
        name=name,
        ssh=ssh_alias,
        label=raw.get("label"),
        status_command=raw.get("status_command"),
        server=_parse_subscription(server_raw, f"hosts.{name}.server"),
        domain=(
            _parse_subscription(domain_raw, f"hosts.{name}.domain", is_domain=True)
            if domain_raw is not None
            else None
        ),
    )


def parse(data: dict, *, source: Path | None = None) -> Config:
    """Build a :class:`Config` from an already-loaded TOML dict."""
    hosts_raw = data.get("hosts", {})
    if not isinstance(hosts_raw, dict):
        raise ConfigError("invalid [hosts] section")

    hosts = {name: _parse_host(name, raw) for name, raw in hosts_raw.items()}

    thresholds = data.get("thresholds", {})
    alerts = data.get("alerts", {})
    notify = data.get("notify", {})
    return Config(
        hosts=hosts,
        warn_days=int(thresholds.get("warn_days", 14)),
        critical_days=int(thresholds.get("critical_days", 7)),
        runway_days=int(alerts.get("runway_days", 14)),
        charge_days=int(alerts.get("charge_days", 7)),
        ntfy=notify.get("ntfy") or None,
        telegram_chat=str(notify["telegram_chat"]) if notify.get("telegram_chat") else None,
        source=source,
    )


def load(path: Path | None = None) -> Config:
    """Load config from disk; returns an empty config if it doesn't exist."""
    path = path or config_path()
    if not path.exists():
        return Config(hosts={})
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML — {exc}") from exc
    return parse(data, source=path)
