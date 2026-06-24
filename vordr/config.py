"""Configuração do Vordr.

A configuração vive em ``~/.config/vordr/config.toml`` (ou em ``$VORDR_CONFIG``).
Você descreve quais hosts monitorar; rode ``vordr init`` para gerar um arquivo
comentado de exemplo. Sem hosts configurados não há o que vigiar.

Nada de IPs nem segredos aqui: os hosts são apenas *aliases* do seu SSH config.
Datas de cobrança/expiração são informadas por você, pois não há como o servidor
saber quando o provedor vai cobrar de novo.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


class ConfigError(RuntimeError):
    """Configuração inválida ou mal formada."""


@dataclass
class Billing:
    """Informações de cobrança/expiração de um host (preenchidas por você)."""

    expires: date | None = None
    cost: float | None = None
    currency: str = "USD"
    cycle: str = "monthly"  # monthly | yearly
    provider: str | None = None

    def days_left(self, today: date | None = None) -> int | None:
        if self.expires is None:
            return None
        today = today or date.today()
        return (self.expires - today).days

    @property
    def monthly_cost(self) -> float | None:
        if self.cost is None:
            return None
        if self.cycle == "yearly":
            return round(self.cost / 12, 2)
        return self.cost


@dataclass
class Host:
    """Um servidor monitorado pelo Vordr."""

    name: str
    ssh: str
    label: str | None = None
    status_command: str | None = None
    billing: Billing = field(default_factory=Billing)

    @property
    def display(self) -> str:
        return self.label or self.name


@dataclass
class Config:
    hosts: dict[str, Host]
    warn_days: int = 14
    critical_days: int = 7
    source: Path | None = None

    def host(self, name: str) -> Host:
        try:
            return self.hosts[name]
        except KeyError:
            known = ", ".join(self.hosts) or "(nenhum)"
            raise ConfigError(f"host '{name}' não configurado. Conhecidos: {known}") from None


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
            raise ConfigError(f"{ctx}: data inválida '{value}' (use AAAA-MM-DD)") from None
    raise ConfigError(f"{ctx}: data inválida '{value!r}'")


def _parse_billing(raw: dict, ctx: str) -> Billing:
    return Billing(
        expires=_parse_date(raw.get("expires"), f"{ctx}.expires"),
        cost=raw.get("cost"),
        currency=raw.get("currency", "USD"),
        cycle=raw.get("cycle", "monthly"),
        provider=raw.get("provider"),
    )


def _parse_host(name: str, raw: dict) -> Host:
    if not isinstance(raw, dict):
        raise ConfigError(f"host '{name}' deve ser uma tabela [hosts.{name}]")
    ssh_alias = raw.get("ssh", name)
    billing_raw = raw.get("billing", {})
    if not isinstance(billing_raw, dict):
        raise ConfigError(f"hosts.{name}.billing deve ser uma tabela")
    return Host(
        name=name,
        ssh=ssh_alias,
        label=raw.get("label"),
        status_command=raw.get("status_command"),
        billing=_parse_billing(billing_raw, f"hosts.{name}.billing"),
    )


def parse(data: dict, *, source: Path | None = None) -> Config:
    """Constrói um :class:`Config` a partir de um dicionário TOML já carregado."""
    hosts_raw = data.get("hosts", {})
    if not isinstance(hosts_raw, dict):
        raise ConfigError("seção [hosts] inválida")

    hosts = {name: _parse_host(name, raw) for name, raw in hosts_raw.items()}

    thresholds = data.get("thresholds", {})
    return Config(
        hosts=hosts,
        warn_days=int(thresholds.get("warn_days", 14)),
        critical_days=int(thresholds.get("critical_days", 7)),
        source=source,
    )


def load(path: Path | None = None) -> Config:
    """Carrega a configuração do disco; usa os padrões embutidos se não existir."""
    path = path or config_path()
    if not path.exists():
        return Config(hosts={})
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: TOML inválido — {exc}") from exc
    return parse(data, source=path)
