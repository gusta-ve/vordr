"""Vordr command-line interface."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

import typer
from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from . import __version__, hetzner, providers, rdap, secrets, ssh, vultr
from .config import Config, ConfigError, Host, Subscription, config_path, load
from .format import (
    days_left_label,
    days_left_style,
    human_age,
    human_kb,
    human_uptime,
    load_style,
    pct_style,
)
from .probe import SecurityMetrics, SystemMetrics, probe_security, probe_system
from .ui import ACCENT, MUTED, brand, card, console, err_console, grid, indent, kv, meta

app = typer.Typer(
    name="vordr",
    help="Vordr — the warden of your servers. Watches status, resources, "
    "cost/expiry and security of your hosts over SSH.",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

CONFIG_TEMPLATE = """\
# Vordr configuration — ~/.config/vordr/config.toml
#
# This file is OPTIONAL: with a token (`vordr secret set hetzner|vultr`) Vordr
# discovers your servers on its own. Use it only for what the API can't know — a
# label, the SSH alias (needed for `status`) or a pinned price (promo/legacy).

[hosts.web]
ssh = "web"                 # alias from ~/.ssh/config (use "" if the host has no SSH)

  [hosts.web.server]
  provider = "Hetzner"      # Hetzner | Vultr — enables automatic cost and since
  # cost = 4.99             # optional: pins a price (wins over the API)
  # currency = "EUR"

  [hosts.web.domain]
  name = "web.example.com"  # expiry comes from RDAP automatically

# Optional per host:  label, status_command
#   [server]: provider_server, since, expires, cost, currency, cycle (monthly|yearly)
#   [domain]: registrar, expires, cost, currency, cycle
# Alert thresholds (default 14/7 days):
# [thresholds]
# warn_days = 14
# critical_days = 7
"""


# --- helpers ---------------------------------------------------------------

def _load_config(*, require_hosts: bool = True) -> Config:
    try:
        config = load()
    except ConfigError as exc:
        err_console.print(f"[bold red]config error:[/] {exc}")
        raise typer.Exit(2) from exc
    if require_hosts and not config.hosts:
        console.print(
            "[yellow]No hosts configured.[/] Run [bold]vordr init[/] and edit "
            f"{config.source or config_path()}."
        )
        raise typer.Exit(0)
    return config


def _select_hosts(config: Config, host: str | None) -> list[Host]:
    if host:
        try:
            return [config.host(host)]
        except ConfigError as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(2) from exc
    return list(config.hosts.values())


def _require_ssh(selected: list[Host]) -> list[Host]:
    """Keep only hosts with an SSH alias; warn about the 'billing-only' ones."""
    usable = [h for h in selected if h.ssh.strip()]
    skipped = [h.display for h in selected if not h.ssh.strip()]
    if skipped:
        console.print(
            f"[dim]no SSH alias (use `vordr cost`/`billing`): {', '.join(skipped)}[/]"
        )
    return usable


def _probe_all(hosts: list[Host], fn) -> dict[str, object]:
    """Run ``fn(host)`` in parallel (SSH I/O is the bottleneck)."""
    results: dict[str, object] = {}
    if not hosts:
        return results
    with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
        futures = {pool.submit(fn, h.ssh): h.name for h in hosts}
        for future in futures:
            name = futures[future]
            results[name] = future.result()
    return results


def _state_text(reachable: bool, error: str | None) -> Text:
    if reachable:
        return Text("● online", style="bold green")
    return Text("● offline", style="bold red")


def _print_host_card(
    display: str, body, *, note: str | None = None, note_style: str = MUTED
) -> None:
    """A frameless per-host card: ``vordr · <host>`` title + indented body."""
    title = brand(display)
    if note:
        title.append("   ")
        title.append(note, style=note_style)
    console.print(card(title, body))


# --- splash ----------------------------------------------------------------

_QUICKSTART = [
    ("vordr cost", "servers, cost & balance at a glance"),
    ("vordr billing", "credit, runway & next charge"),
    ("vordr status", "are they up? load, ram, disk, docker"),
]


def _splash() -> None:
    """Branded banner for the bare command (full help lives behind `-h`)."""
    console.print()
    console.print(
        f"  [bold {ACCENT}]vordr[/][{MUTED}]  ·  the warden of your servers[/]"
        f"   [{MUTED}]v{__version__}[/]"
    )
    console.print(f"  [{MUTED}]gusta-ve · github.com/gusta-ve/vordr · your fleet, one glance[/]")
    console.print(f"  [{MUTED}]Vörðr · the Norse guardian spirit[/]")
    console.print()
    for cmd, desc in _QUICKSTART:
        console.print(f"  [{ACCENT}]{cmd:<16}[/][{MUTED}]{desc}[/]")
    console.print()
    console.print(f"  [{MUTED}]vordr -h  ·  full help, every command and option[/]")


# --- commands --------------------------------------------------------------

@app.command()
def hosts() -> None:
    """List the configured hosts (without contacting them)."""
    config = _load_config()
    table = grid("host", "ssh", "status cmd", "provider", "expires")
    for h in config.hosts.values():
        s = h.server
        table.add_row(
            Text(h.display, style="bold"),
            Text(h.ssh, style=ACCENT),
            Text(h.status_command or "—", style=MUTED),
            s.provider or "—",
            s.expires.isoformat() if s.expires else "—",
        )
    console.print()
    console.print(indent(brand("hosts")))
    console.print()
    console.print(indent(table))
    console.print(indent(meta(f"source: {config.source or config_path()}")))


def _is_interactive() -> bool:
    """Is there a real terminal to ask questions? (false in pipes/tests)."""
    return sys.stdin.isatty()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing config."),
) -> None:
    """Create the config. In a terminal, becomes a wizard that imports your servers.

    With a saved token, ``init`` lists the account's servers and builds the config for
    you — no hand-written TOML. Without a terminal (pipe/CI) or without a token, it
    writes a commented template.
    """
    path = config_path()
    interactive = _is_interactive()
    if path.exists() and not force:
        overwrite = interactive and typer.confirm(
            f"{path} already exists. Overwrite?", default=False
        )
        if not overwrite:
            err_console.print(
                f"[yellow]already exists:[/] {path}\nUse [bold]--force[/] to overwrite."
            )
            raise typer.Exit(1)

    blocks = _wizard_import() if interactive else []
    content = _render_config(blocks) if blocks else CONFIG_TEMPLATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    console.print(f"[green]✔[/] config created at [bold]{path}[/]")
    if blocks:
        console.print(
            f"[dim]{len(blocks)} host(s) imported. Run `vordr cost` or `vordr status`.[/dim]"
        )
    else:
        console.print(
            "[dim]edit the hosts (or run `vordr secret set` and `vordr init` again "
            "to import from the API) and use `vordr cost`.[/dim]"
        )


def _suggest_alias(name: str, aliases: list[str]) -> str | None:
    """Match a server name to an SSH alias (equality or substring)."""
    low = name.lower()
    for alias in aliases:
        al = alias.lower()
        if al == low or al in low or low in al:
            return alias
    return None


def _toml_key(value: str, used: set[str]) -> str:
    """A safe, unique TOML table key (A-Za-z0-9_-)."""
    base = "".join(c if (c.isalnum() or c in "_-") else "-" for c in value).strip("-") or "host"
    key, n = base, 2
    while key in used:
        key, n = f"{base}-{n}", n + 1
    used.add(key)
    return key


def _render_host_block(key: str, alias: str, provider: str, sb, cost: float | None) -> str:
    if alias:
        ssh_line = f'ssh = "{alias}"'
    else:
        ssh_line = 'ssh = ""   # no SSH alias: shows in cost/billing, not status'
    lines = [
        f"[hosts.{key}]",
        ssh_line,
        f'label = "{sb.name}"',
        "",
        f"  [hosts.{key}.server]",
        f'  provider = "{provider}"',
    ]
    if cost is not None:
        lines.append(f"  cost = {cost}")
        lines.append(f'  currency = "{sb.currency}"')
        lines.append("  # pinned price (wins over the API). Delete to use the API value.")
    else:
        lines.append("  # cost and since come from the API automatically (list price).")
    return "\n".join(lines)


def _render_config(blocks: list[str]) -> str:
    header = (
        "# Vordr configuration — generated by `vordr init`.\n"
        "# Blank fields are filled from the API/RDAP; what you write wins.\n\n"
        "[thresholds]\n"
        "warn_days = 14\n"
        "critical_days = 7\n\n"
    )
    return header + "\n\n".join(blocks) + "\n"


def _wizard_import() -> list[str]:
    """Interactive wizard: discover servers via the API and build config blocks."""
    tokened = [p for p in _PROVIDER_CLIENTS if secrets.get_token(p)]
    if not tokened:
        console.print("[dim]No provider token saved.[/]")
        choice = typer.prompt(
            f"Set one now? Provider ({'/'.join(secrets.ENV_VARS)}) or enter to skip",
            default="",
            show_default=False,
        ).strip().lower()
        if choice in secrets.ENV_VARS and _store_token_flow(choice):
            tokened = [choice]
        if not tokened:
            return []

    discovered: dict[str, dict[str, providers.ServerBilling]] = {}
    for prov in tokened:
        try:
            discovered[prov] = _PROVIDER_CLIENTS[prov].fetch_servers(
                secrets.get_token(prov), timeout=15
            )
        except providers.ProviderError as exc:
            err_console.print(f"[red]{prov}: {exc}[/]")

    total = sum(len(c) for c in discovered.values())
    if not total:
        console.print("[yellow]No servers found in the accounts.[/]")
        return []
    console.print(f"[cyan]{total} server(s) found.[/] Map each one:")

    aliases = ssh.list_aliases()
    blocks: list[str] = []
    used: set[str] = set()
    for prov in sorted(discovered):
        for name, sb in sorted(discovered[prov].items()):
            if not typer.confirm(f"  import '{name}' ({prov.capitalize()})?", default=True):
                continue
            suggestion = _suggest_alias(name, aliases)
            if suggestion:
                alias = typer.prompt(
                    "    SSH alias (for status/resources)", default=suggestion
                ).strip()
            else:
                alias = typer.prompt(
                    "    SSH alias (enter if none — cost/billing only)",
                    default="",
                    show_default=False,
                ).strip()
            api_hint = (
                f"{sb.currency} {sb.cost_gross:.2f}"
                if sb.cost_gross is not None
                else "unknown"
            )
            cost_in = typer.prompt(
                f"    fixed price/mo? (enter = use the API: {api_hint})",
                default="",
                show_default=False,
            ).strip()
            cost: float | None = None
            if cost_in:
                try:
                    cost = round(float(cost_in.replace(",", ".")), 2)
                except ValueError:
                    console.print("[yellow]    invalid value — using the API's.[/]")
            key = _toml_key(alias or name, used)
            blocks.append(_render_host_block(key, alias, prov.capitalize(), sb, cost))
    return blocks


secret_app = typer.Typer(
    help="Manage provider API tokens — stored outside the repository.",
    no_args_is_help=True,
)
app.add_typer(secret_app, name="secret")


def _store_token_flow(provider: str) -> bool:
    """Prompt, validate (one API read) and store the token. True if stored."""
    token = typer.prompt(f"API token ({provider})", hide_input=True).strip()
    if not token:
        err_console.print("[red]empty token.[/]")
        return False
    client = _PROVIDER_CLIENTS.get(provider)
    if client is not None:  # validate with a read before storing
        try:
            client.fetch_servers(token, timeout=15)
        except providers.ProviderError as exc:
            err_console.print(f"[red]token rejected:[/] {exc}")
            return False
    path = secrets.set_token(provider, token)
    console.print(f"[green]✔[/] [bold]{provider}[/] token saved to [bold]{path}[/] (chmod 600)")
    return True


@secret_app.command("set")
def secret_set(
    provider: str = typer.Argument(..., help=f"One of: {', '.join(secrets.ENV_VARS)}."),
) -> None:
    """Save (and validate) a provider's API token in ~/.config/vordr/secrets.toml."""
    provider = provider.lower()
    if provider not in secrets.ENV_VARS:
        err_console.print(
            f"[red]unknown provider:[/] {provider} "
            f"(known: {', '.join(secrets.ENV_VARS)})"
        )
        raise typer.Exit(2)
    if not _store_token_flow(provider):
        raise typer.Exit(1)
    console.print(
        f"[dim]the {secrets.ENV_VARS[provider]} environment variable takes precedence "
        f"over the file, if set.[/dim]"
    )


@secret_app.command("status")
def secret_status() -> None:
    """Show which providers have a token configured (without revealing it)."""
    table = grid("provider", "source", "token")
    labels = {"env": None, "file": "file"}
    for prov in sorted(secrets.ENV_VARS):
        src = secrets.token_source(prov)
        tok = secrets.get_token(prov)
        source = f"env ({secrets.ENV_VARS[prov]})" if src == "env" else labels.get(src) or "—"
        table.add_row(
            Text(prov, style="bold"),
            source,
            Text(secrets.mask(tok), style=ACCENT) if tok else Text("not set", style=MUTED),
        )
    console.print()
    console.print(indent(brand("api tokens")))
    console.print()
    console.print(indent(table))


def _build_status_table(
    config: Config, metrics: dict[str, SystemMetrics], today: date
) -> Group:
    table = grid("host", "state", "uptime", "load", "ram", "disk", "docker", "expires")

    for name, host in config.hosts.items():
        m = metrics[name]
        days = host.server.days_left(today)

        if not m.reachable:
            table.add_row(
                Text(host.display, style="bold"),
                _state_text(False, m.error),
                Text(m.error or "unreachable", style="red"),
                "—", "—", "—", "—",
                Text(days_left_label(days), style=days_left_style(
                    days, warn=config.warn_days, critical=config.critical_days)),
            )
            continue

        load_txt = Text(
            f"{m.load1:.2f}" if m.load1 is not None else "—",
            style=load_style(m.load_per_cpu),
        )
        ram_txt = Text(
            f"{m.mem_used_pct}%" if m.mem_used_pct is not None else "—",
            style=pct_style(m.mem_used_pct),
        )
        disk_txt = Text(
            f"{m.disk_pct}%" if m.disk_pct is not None else "—",
            style=pct_style(m.disk_pct),
        )
        docker_txt = (
            f"{m.docker_running}/{m.docker_total}"
            if m.docker_running is not None
            else "—"
        )
        table.add_row(
            Text(host.display, style="bold"),
            _state_text(True, None),
            human_uptime(m.uptime_seconds),
            load_txt,
            ram_txt,
            disk_txt,
            docker_txt,
            Text(days_left_label(days), style=days_left_style(
                days, warn=config.warn_days, critical=config.critical_days)),
        )
    return Group(Text(), indent(brand("server status")), Text(), indent(table))


@app.command()
def status(
    host: str = typer.Argument(None, help="Specific host (default: all)."),
    raw: bool = typer.Option(
        False, "--raw", help="Show the host's native status_command output."
    ),
    watch: float = typer.Option(
        0, "--watch", "-w", help="Refresh every N seconds (0 = once)."
    ),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="SSH timeout per host (s)."),
) -> None:
    """Status board: state, uptime, load, RAM, disk, containers and expiry."""
    config = _load_config()
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)

    if raw:
        for h in selected:
            if not h.status_command:
                err_console.print(f"[yellow]{h.display}: no status_command set[/]")
                continue
            console.rule(f"[bold cyan]{h.display}[/]")
            try:
                ssh.run_passthrough(h.ssh, h.status_command, timeout=timeout)
            except ssh.SSHError as exc:
                err_console.print(f"[red]{h.display}: {exc}[/]")
        return

    def render() -> Table:
        metrics = _probe_all(selected, lambda a: probe_system(a, timeout=timeout))
        sub = Config(hosts={h.name: h for h in selected},
                     warn_days=config.warn_days, critical_days=config.critical_days)
        return _build_status_table(sub, metrics, date.today())

    if watch and watch > 0:
        with Live(render(), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                time.sleep(watch)
                live.update(render())
    else:
        console.print(render())


@app.command()
def resources(
    host: str = typer.Argument(None, help="Specific host (default: all)."),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="SSH timeout per host (s)."),
) -> None:
    """Resource detail: CPU/load, memory and disk with absolute values."""
    config = _load_config()
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)
    metrics = _probe_all(selected, lambda a: probe_system(a, timeout=timeout))

    console.print()
    for h in selected:
        m: SystemMetrics = metrics[h.name]  # type: ignore[assignment]
        if not m.reachable:
            _print_host_card(h.display, Text(m.error or "unreachable", style="red"),
                              note="offline", note_style="red")
            continue

        table = kv()
        table.add_row("OS", m.os or "—")
        table.add_row("uptime", human_uptime(m.uptime_seconds))
        load_line = (
            f"{', '.join(f'{x:.2f}' for x in m.loadavg)}  ({m.cpus} CPUs"
            f", {m.load_per_cpu}/cpu)"
            if m.loadavg else "—"
        )
        table.add_row("load", Text(load_line, style=load_style(m.load_per_cpu)))
        if m.mem_total_kb:
            used = m.mem_total_kb - (m.mem_avail_kb or 0)
            table.add_row(
                "memory",
                Text(
                    f"{human_kb(used)} / {human_kb(m.mem_total_kb)} ({m.mem_used_pct}%)",
                    style=pct_style(m.mem_used_pct),
                ),
            )
        if m.disk_total_kb:
            table.add_row(
                "disk /",
                Text(
                    f"{human_kb(m.disk_used_kb)} / {human_kb(m.disk_total_kb)} "
                    f"({m.disk_pct}%)",
                    style=pct_style(m.disk_pct),
                ),
            )
        if m.docker_running is not None:
            table.add_row("docker", f"{m.docker_running} running / {m.docker_total} total")
        table.add_row("sessions", str(m.users) if m.users is not None else "—")

        _print_host_card(h.display, table)


@app.command()
def security(
    host: str = typer.Argument(None, help="Specific host (default: all)."),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="SSH timeout per host (s)."),
) -> None:
    """Security audit: logins, failures, ports, fail2ban and updates."""
    config = _load_config()
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)
    metrics = _probe_all(selected, lambda a: probe_security(a, timeout=timeout))

    console.print()
    for h in selected:
        s: SecurityMetrics = metrics[h.name]  # type: ignore[assignment]
        if not s.reachable:
            _print_host_card(h.display, Text(s.error or "unreachable", style="red"),
                             note="offline", note_style="red")
            continue

        table = kv()

        fail_style = "green" if not s.failed_logins else (
            "bold red" if s.failed_logins > 50 else "yellow")
        table.add_row("active sessions", str(s.users_now) if s.users_now is not None else "—")
        table.add_row(
            "failed logins",
            Text(str(s.failed_logins) if s.failed_logins is not None else "—",
                 style=fail_style),
        )
        if s.ports:
            ports = " ".join(str(p) for p in s.ports)
            table.add_row("listening ports", ports)
        table.add_row("fail2ban", s.fail2ban or Text("not detected", style="yellow"))
        if s.updates is not None:
            up_style = "green" if s.updates == 0 else "yellow"
            table.add_row("updates", Text(str(s.updates), style=up_style))
        if s.reboot_required:
            table.add_row("reboot", Text("required", style="bold red"))
        if s.last_logins:
            table.add_row("last logins", "\n".join(s.last_logins))

        # simple verdict
        warnings = []
        if s.failed_logins and s.failed_logins > 50:
            warnings.append("many failed logins")
        if s.reboot_required:
            warnings.append("reboot pending")
        if s.updates and s.updates > 0:
            warnings.append(f"{s.updates} updates")
        verdict, vstyle = (
            ("⚠ attention: " + ", ".join(warnings), "yellow")
            if warnings
            else ("✔ no alerts", "green")
        )
        _print_host_card(h.display, table, note=verdict, note_style=vstyle)


# --- lifecycle: resolve config (manual) > provider API > RDAP -----------------

# Providers with a built-in API client. The MANUAL config value always wins over
# what comes from here — it's the "fallback path" for promo/legacy prices. We store
# the *module* (not the function) so `.fetch_servers` is resolved at call time —
# letting tests monkeypatch it.
_PROVIDER_CLIENTS = {
    "hetzner": hetzner,
    "vultr": vultr,
}


@dataclass
class _Lifecycle:
    """A host's effective values after merging config, provider API and RDAP."""

    since: date | None = None
    since_auto: bool = False
    cost: float | None = None  # monthly server cost (normalized)
    cost_net: float | None = None  # net, when it differs from what's charged (via API)
    currency: str = "USD"
    cost_auto: bool = False
    domain_expiry: date | None = None
    domain_expiry_auto: bool = False


def _money(totals: dict[str, float]) -> str:
    if not totals:
        return "—"
    return " + ".join(f"{cur} {val:.2f}" for cur, val in sorted(totals.items()))


def _monthly_by_currency(host: Host, lc: _Lifecycle) -> dict[str, float]:
    """Monthly cost of server + domain (server may come from the API), by currency."""
    totals: dict[str, float] = {}
    if lc.cost is not None:
        totals[lc.currency] = round(totals.get(lc.currency, 0.0) + lc.cost, 2)
    dom = host.domain
    if dom is not None and dom.monthly_cost is not None:
        totals[dom.currency] = round(totals.get(dom.currency, 0.0) + dom.monthly_cost, 2)
    return totals


def _renewal_cell(
    expires: date | None, has_data: bool, config: Config, today: date
) -> Text:
    """A 'Xd left  YYYY-MM-DD' cell colored by threshold (or '—')."""
    if expires is None and not has_data:
        return Text("—", style="dim")
    days = (expires - today).days if expires else None
    suffix = f"  {expires.isoformat()}" if expires else ""
    return Text(
        days_left_label(days) + suffix,
        style=days_left_style(days, warn=config.warn_days, critical=config.critical_days),
    )


def _resolve_domain_expiries(
    hosts: list[Host], *, offline: bool, timeout: int
) -> dict[str, date | None]:
    """Resolve the domain expiry of several hosts (RDAP in parallel)."""
    resolved: dict[str, date | None] = {}
    pending: list[Host] = []
    for h in hosts:
        if h.domain is not None and h.domain.expires is not None:
            resolved[h.name] = h.domain.expires
        elif h.domain is not None and h.domain.name and not offline:
            resolved[h.name] = None  # placeholder; filled by RDAP
            pending.append(h)
        else:
            resolved[h.name] = None
    if pending:
        with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
            futures = {
                pool.submit(rdap.domain_expiry, h.domain.name, timeout=timeout): h.name
                for h in pending
            }
            for future in futures:
                resolved[futures[future]] = future.result()
    return resolved


def _referenced_providers(hosts: list[Host]) -> set[str]:
    """Providers explicitly named by the config hosts."""
    return {
        h.server.provider.lower()
        for h in hosts
        if h.server.provider and h.server.provider.lower() in _PROVIDER_CLIENTS
    }


def _api_providers(hosts: list[Host]) -> list[str]:
    """Providers to query: those referenced in config + those with a saved token."""
    referenced = _referenced_providers(hosts)
    with_token = {p for p in _PROVIDER_CLIENTS if secrets.get_token(p)}
    return sorted(referenced | with_token)


def _fetch_provider_servers(
    hosts: list[Host], *, timeout: int, discover: bool = False
) -> tuple[dict[str, dict[str, providers.ServerBilling]], list[str]]:
    """List servers from the provider APIs. Returns (data, notes).

    With ``discover=True`` it also queries every provider that has a saved token (not
    only those named in config) — this is what finds servers with no TOML entry at all.
    Without a token, it only warns for providers actually referenced by a host.
    """
    servers: dict[str, dict[str, providers.ServerBilling]] = {}
    notes: list[str] = []
    referenced = _referenced_providers(hosts)
    query = set(referenced)
    if discover:
        query |= {p for p in _PROVIDER_CLIENTS if secrets.get_token(p)}
    for prov in sorted(query):
        token = secrets.get_token(prov)
        if not token:
            if prov in referenced:
                notes.append(
                    f"{prov}: no token — run `vordr secret set {prov}` to automate"
                )
            continue
        try:
            servers[prov] = _PROVIDER_CLIENTS[prov].fetch_servers(token, timeout=timeout)
        except providers.ProviderError as exc:
            notes.append(f"{prov}: {exc}")
    return servers, notes


def _discovered_host(prov: str, sb: providers.ServerBilling) -> Host:
    """A synthetic host from a server found in the API (no config entry).

    No ``ssh`` (so it's out of status/resources/security); cost and ``since`` flow from
    the API via :func:`_resolve_lifecycle`.
    """
    return Host(
        name=sb.name,
        ssh="",
        label=sb.name,
        server=Subscription(provider=prov.capitalize(), provider_ref=sb.name),
    )


def _assemble_rows(
    config_hosts: list[Host],
    servers: dict[str, dict[str, providers.ServerBilling]],
    dom_exp: dict[str, date | None],
    today: date,
    *,
    discover: bool,
) -> list[tuple[Host, _Lifecycle]]:
    """Join config hosts (enriched by the API) with servers found only in the API."""
    rows: list[tuple[Host, _Lifecycle]] = []
    claimed: set[tuple[str, str]] = set()
    for h in config_hosts:
        sb = _match_server(h, servers)
        if sb is not None and h.server.provider:
            claimed.add((h.server.provider.lower(), sb.name))
        rows.append((h, _resolve_lifecycle(h, sb, dom_exp.get(h.name), today)))
    if discover:
        for prov in sorted(servers):
            for name, sb in sorted(servers[prov].items()):
                if (prov, name) in claimed:
                    continue
                host = _discovered_host(prov, sb)
                rows.append((host, _resolve_lifecycle(host, sb, None, today)))
    return rows


def _find_row(
    rows: list[tuple[Host, _Lifecycle]], name: str
) -> tuple[Host, _Lifecycle] | None:
    """Find a host's row by name/label/SSH alias (config or discovered)."""
    low = name.lower()
    for host, lc in rows:
        if low in {host.name.lower(), (host.label or "").lower(), host.ssh.lower()}:
            return host, lc
    return None


def _match_server(
    host: Host, servers: dict[str, dict[str, providers.ServerBilling]]
) -> providers.ServerBilling | None:
    """Match a host to its API server (by provider_server, alias, name or label)."""
    catalog = servers.get((host.server.provider or "").lower())
    if not catalog:
        return None
    for ref in (host.server.provider_ref, host.ssh, host.name, host.label):
        if not ref:
            continue
        low = ref.lower()
        for name, billing in catalog.items():
            if low == name.lower() or low in name.lower():
                return billing
    return None


def _resolve_lifecycle(
    host: Host, sb: providers.ServerBilling | None, dom_expiry: date | None, today: date
) -> _Lifecycle:
    srv = host.server
    since, since_auto = srv.since, False
    if since is None and sb is not None and sb.created is not None:
        since, since_auto = sb.created, True

    cost, currency, cost_net, cost_auto = srv.monthly_cost, srv.currency, None, False
    if cost is None and sb is not None and sb.cost_gross is not None:
        cost = sb.cost_gross
        cost_net = sb.cost_net if sb.cost_net != sb.cost_gross else None
        currency = sb.currency
        cost_auto = True

    dom = host.domain
    dom_auto = dom is not None and dom.expires is None and dom_expiry is not None
    return _Lifecycle(since, since_auto, cost, cost_net, currency, cost_auto, dom_expiry, dom_auto)


def _age_text(lc: _Lifecycle, today: date) -> str:
    return human_age((today - lc.since).days) if lc.since else "—"


def _cost_table(
    rows: list[tuple[Host, _Lifecycle]], config: Config, today: date
) -> Table:
    table = grid("host", "provider", "hosting for", "server", "domain", "cost/mo",
                 right=("cost/mo",))
    for host, lc in rows:
        dom = host.domain
        dom_has = dom is not None and (dom.has_data or bool(dom.name))
        table.add_row(
            Text(host.display, style="bold"),
            host.server.provider or "—",
            _age_text(lc, today),
            _renewal_cell(host.server.expires, host.server.has_data, config, today),
            _renewal_cell(lc.domain_expiry, dom_has, config, today),
            _money(_monthly_by_currency(host, lc)),
        )
    return table


def _cost_panel(host: Host, config: Config, today: date, lc: _Lifecycle) -> Group:
    srv, dom = host.server, host.domain
    table = kv()

    table.add_row("provider", srv.provider or "—")
    age_line = Text(_age_text(lc, today))
    if lc.since:
        age_line.append(f"  (since {lc.since.isoformat()})", style=MUTED)
        if lc.since_auto:
            age_line.append("  (API)", style=f"italic {MUTED}")
    table.add_row("hosting for", age_line)

    table.add_row("server renews", _renewal_cell(srv.expires, srv.has_data, config, today))
    if lc.cost is not None:
        money = Text(f"{lc.currency} {lc.cost:.2f} / mo", style=MUTED)
        if lc.cost_auto:
            money.append("  (API)", style=f"italic {MUTED}")
        table.add_row("", money)
        if lc.cost_net is not None:
            table.add_row("", Text(f"net {lc.currency} {lc.cost_net:.2f}", style=MUTED))

    if dom is not None and (lc.domain_expiry is not None or dom.has_data or dom.name):
        cell = _renewal_cell(lc.domain_expiry, dom.has_data or bool(dom.name), config, today)
        if lc.domain_expiry_auto:
            cell.append("  (RDAP)", style=f"italic {MUTED}")
        table.add_row("domain expires", cell)
        detail = " · ".join(p for p in (dom.name, dom.provider) if p)
        if detail:
            table.add_row("", Text(detail, style=MUTED))
        if dom.cost is not None:
            table.add_row("", Text(f"{dom.currency} {dom.cost:.2f} / {dom.cycle}", style=MUTED))
    else:
        table.add_row("domain", Text("not set", style=MUTED))

    table.add_row("cost/mo", Text(_money(_monthly_by_currency(host, lc)),
                                  style=f"bold {ACCENT}"))
    return card(brand(host.display), table)


@app.command()
def cost(
    host: str = typer.Argument(
        None, help="Specific host → detailed panel (default: table of all)."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Don't query the network (RDAP/API); use the config only."
    ),
    timeout: int = typer.Option(
        rdap.DEFAULT_TIMEOUT, help="Network query timeout — RDAP and API (s)."
    ),
) -> None:
    """Cost & lifecycle: hosting, server renewal and domain expiry.

    With a saved token it **discovers the account's servers** automatically — the config
    is optional. Config values always win; whatever's missing comes from the API
    (cost/``since``) and RDAP (domain expiry). Use ``--offline`` for config only, no network.
    """
    config = _load_config(require_hosts=False)
    today = date.today()
    config_hosts = list(config.hosts.values())
    discover = not offline

    servers: dict[str, dict[str, providers.ServerBilling]] = {}
    notes: list[str] = []
    accounts: dict[str, providers.AccountBilling] = {}
    if not offline:
        servers, notes = _fetch_provider_servers(config_hosts, timeout=timeout, discover=discover)
        accounts, acct_notes = _fetch_provider_accounts(config_hosts, timeout=timeout)
        notes += acct_notes
    dom_exp = _resolve_domain_expiries(config_hosts, offline=offline, timeout=timeout)
    rows = _assemble_rows(config_hosts, servers, dom_exp, today, discover=discover)

    if not rows:
        console.print(
            "[yellow]Nothing to show.[/] Set a token "
            "([bold]vordr secret set hetzner|vultr[/]) to discover servers via the API, "
            "or [bold]vordr init[/] to declare hosts over SSH."
        )
        for note in notes:
            console.print(f"[dim yellow]{note}[/]")
        raise typer.Exit(0)

    if host:
        row = _find_row(rows, host)
        if row is None:
            known = ", ".join(sorted(h.display for h, _ in rows)) or "(none)"
            err_console.print(f"[bold red]host '{host}' not found.[/] Known: {known}")
            raise typer.Exit(2)
        console.print()
        console.print(_cost_panel(row[0], config, today, row[1]))
    else:
        console.print()
        console.print(indent(brand("cost & lifecycle")))
        console.print()
        console.print(indent(_cost_table(rows, config, today)))

        totals: dict[str, float] = {}
        missing: list[str] = []
        for h, lc in rows:
            for cur, val in _monthly_by_currency(h, lc).items():
                totals[cur] = round(totals.get(cur, 0.0) + val, 2)
            has_any = (
                lc.cost is not None
                or lc.since is not None
                or lc.domain_expiry is not None
                or (h.domain is not None and h.domain.has_data)
            )
            if not has_any:
                missing.append(h.display)

        console.print()
        if totals:
            console.print(indent(meta(f"total  {_money(totals)}")))
        if missing:
            console.print(indent(meta(
                f"no billing data: {', '.join(missing)} — "
                f"edit {config.source or config_path()}"
            )))

    for prov in sorted(accounts):
        burn, _cur = _provider_monthly_burn(rows, prov)
        console.print(indent(_billing_summary_line(prov, accounts[prov], burn, today)))

    for note in notes:
        console.print(indent(meta(note)))


# --- balance & billing per provider ------------------------------------------

def _billing_model(prov: str) -> str:
    """'prepaid' (credit/balance) or 'postpaid' (card) — declared by the module."""
    return getattr(_PROVIDER_CLIENTS.get(prov), "BILLING_MODEL", "postpaid")


def _first_of_next_month(today: date) -> date:
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def _fetch_provider_accounts(
    hosts: list[Host], *, timeout: int
) -> tuple[dict[str, providers.AccountBilling], list[str]]:
    """Account balance for providers that expose ``fetch_account``."""
    accounts: dict[str, providers.AccountBilling] = {}
    notes: list[str] = []
    for prov in _api_providers(hosts):
        client = _PROVIDER_CLIENTS[prov]
        if not hasattr(client, "fetch_account"):
            continue  # postpaid provider — no balance via API
        token = secrets.get_token(prov)
        if not token:
            continue  # a missing token is already flagged by the server fetch
        try:
            accounts[prov] = client.fetch_account(token, timeout=timeout)
        except providers.ProviderError as exc:
            notes.append(f"{prov}: {exc}")
    return accounts, notes


def _provider_monthly_burn(
    rows: list[tuple[Host, _Lifecycle]], prov: str
) -> tuple[float | None, str | None]:
    """Sum the monthly cost of a provider's hosts (the 'burn' that eats the balance)."""
    total, currency, found = 0.0, None, False
    for host, lc in rows:
        if (host.server.provider or "").lower() != prov:
            continue
        if lc.cost is not None:
            total += lc.cost
            currency = lc.currency
            found = True
    return (round(total, 2), currency) if found else (None, None)


def _runway(
    net_remaining: float | None, monthly_burn: float | None, today: date
) -> tuple[int | None, date | None]:
    """Days until the credit runs out, given the monthly burn."""
    if net_remaining is None or not monthly_burn or monthly_burn <= 0:
        return None, None
    daily = monthly_burn / 30.0
    days = int(net_remaining / daily)
    return days, today + timedelta(days=days)


def _billing_summary_line(
    prov: str, acct: providers.AccountBilling, burn: float | None, today: date
) -> Text:
    """Short line for the `cost` footer (credit + runway)."""
    parts = [prov.capitalize()]
    cr = acct.credit
    if cr is not None:
        parts.append(f"credit {acct.currency} {cr:.2f}")
    if acct.pending_charges:
        parts.append(f"pending {acct.currency} {acct.pending_charges:.2f}")
    net = acct.net_remaining
    if net is not None:
        parts.append(f"net {acct.currency} {net:.2f}")
    days, runout = _runway(net, burn, today)
    if days is not None and runout is not None:
        parts.append(f"runway ~{days}d → {runout.isoformat()}")
    return meta(*parts)


def _billing_panel(
    prov: str,
    acct: providers.AccountBilling | None,
    burn: float | None,
    currency: str | None,
    config: Config,
    today: date,
    offline: bool,
) -> Group:
    table = kv()

    if _billing_model(prov) == "prepaid":
        table.add_row("model", "prepaid (credit/balance)")
        if acct is None:
            if offline:
                detail = Text("— (offline)", style=MUTED)
            elif not secrets.get_token(prov):
                detail = Text(f"no token — run `vordr secret set {prov}`", style="yellow")
            else:
                detail = Text("unavailable", style=MUTED)
            table.add_row("balance", detail)
        else:
            cr = acct.credit
            if cr is not None:
                table.add_row("credit", f"{acct.currency} {cr:.2f}")
            if acct.pending_charges:
                table.add_row("pending", f"{acct.currency} {acct.pending_charges:.2f}")
            net = acct.net_remaining
            if net is not None:
                table.add_row("net", Text(f"{acct.currency} {net:.2f}", style=f"bold {ACCENT}"))
            days, runout = _runway(net, burn, today)
            if days is not None and runout is not None:
                style = days_left_style(days, warn=config.warn_days, critical=config.critical_days)
                table.add_row(
                    "runway",
                    Text(f"~{days} days  (runs out {runout.isoformat()})", style=style),
                )
                table.add_row(
                    "billing", Text("on credit — no card until the balance runs out", style=MUTED)
                )
            else:
                table.add_row("billing", Text("on credit", style=MUTED))
    else:  # postpaid — charged to the card, fixed calendar
        table.add_row("model", "postpaid (card)")
        nxt = _first_of_next_month(today)
        days = (nxt - today).days
        est = f"  (≈ {currency} {burn:.2f} / mo)" if burn is not None and currency else ""
        table.add_row(
            "next charge",
            Text(
                f"{nxt.isoformat()}  (in {days}d){est}",
                style=days_left_style(days, warn=config.warn_days, critical=config.critical_days),
            ),
        )
        table.add_row(
            "balance", Text(f"— (not exposed by the {prov.capitalize()} API)", style=MUTED)
        )

    return card(brand(prov.capitalize()), table)


@app.command()
def billing(
    offline: bool = typer.Option(
        False, "--offline", help="Don't query the API; show only the billing model."
    ),
    timeout: int = typer.Option(
        rdap.DEFAULT_TIMEOUT, help="Provider API query timeout (s)."
    ),
) -> None:
    """Balance, credit and next charge per provider.

    For prepaid providers (e.g. Vultr) it shows credit, pending usage and the
    *runway* — when the balance runs out and the card charges begin. For postpaid ones
    (e.g. Hetzner) it shows the next charge date and the estimated cost.
    """
    config = _load_config(require_hosts=False)
    hosts = list(config.hosts.values())
    today = date.today()
    discover = not offline

    servers: dict[str, dict[str, providers.ServerBilling]] = {}
    notes: list[str] = []
    accounts: dict[str, providers.AccountBilling] = {}
    if not offline:
        servers, notes = _fetch_provider_servers(hosts, timeout=timeout, discover=discover)
        accounts, acct_notes = _fetch_provider_accounts(hosts, timeout=timeout)
        notes += acct_notes
    rows = _assemble_rows(hosts, servers, {}, today, discover=discover)

    providers_seen = sorted(
        {(h.server.provider or "").lower() for h, _ in rows} & set(_PROVIDER_CLIENTS)
    )
    if not providers_seen:
        console.print(
            "[yellow]No API provider to show.[/] Set a token "
            '([bold]vordr secret set hetzner|vultr[/]) or set provider = "Hetzner"/"Vultr".'
        )
        for note in notes:
            console.print(f"[dim yellow]{note}[/]")
        raise typer.Exit(0)

    console.print()
    for prov in providers_seen:
        burn, currency = _provider_monthly_burn(rows, prov)
        console.print(
            _billing_panel(prov, accounts.get(prov), burn, currency, config, today, offline)
        )

    for note in notes:
        console.print(indent(meta(note)))


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"vordr {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Vordr stands guard over your servers."""
    if ctx.invoked_subcommand is None:
        _splash()


if __name__ == "__main__":  # pragma: no cover
    app()
