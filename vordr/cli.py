"""Interface de linha de comando do Vordr."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, rdap, ssh
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

app = typer.Typer(
    name="vordr",
    help="Vordr — guardião dos servidores. Monitora status, recursos, "
    "custo/expiração e segurança dos seus hosts via SSH.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

CONFIG_TEMPLATE = """\
# Configuração do Vordr — ~/.config/vordr/config.toml
#
# Os hosts são apenas ALIASES do seu ~/.ssh/config. Nenhum IP ou segredo aqui.
# As datas de cobrança/expiração são informadas por você (o servidor não sabe
# quando o provedor ou o registrar vão cobrar de novo).
#
# Cada host tem dois blocos opcionais de ciclo de vida:
#   [hosts.X.server]  — a hospedagem (provedor, desde quando, renovação, custo)
#   [hosts.X.domain]  — o domínio    (registrar, expiração, custo)

[thresholds]
warn_days = 14       # avisa (amarelo) quando faltar <= esta qtd de dias
critical_days = 7    # alerta (vermelho) quando faltar <= esta qtd de dias

[hosts.web]
ssh = "web"                   # alias no ~/.ssh/config
label = "Web"
# status_command = "meu-status"   # opcional: seu script p/ `vordr status --raw`

  [hosts.web.server]
  provider = "Hetzner"
  since   = "2024-03-01"      # desde quando você hospeda aqui (tempo de hospedagem)
  expires = "2026-08-15"      # AAAA-MM-DD — próxima renovação do servidor
  cost = 6.99
  currency = "USD"
  cycle = "monthly"           # monthly | yearly

  [hosts.web.domain]
  name = "web.exemplo.com"
  registrar = "Cloudflare"
  expires = "2027-03-01"      # quando o domínio expira
  cost = 12.00
  currency = "USD"
  cycle = "yearly"

[hosts.db]
ssh = "db"
label = "DB"

  [hosts.db.server]
  provider = "DigitalOcean"
  since   = "2025-01-10"
  expires = "2026-07-30"
  cost = 12.00
  currency = "USD"
  cycle = "monthly"
"""


# --- helpers ---------------------------------------------------------------

def _load_config(*, require_hosts: bool = True) -> Config:
    try:
        config = load()
    except ConfigError as exc:
        err_console.print(f"[bold red]erro de configuração:[/] {exc}")
        raise typer.Exit(2) from exc
    if require_hosts and not config.hosts:
        console.print(
            "[yellow]Nenhum host configurado.[/] Rode [bold]vordr init[/] e edite "
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


def _probe_all(hosts: list[Host], fn) -> dict[str, object]:
    """Executa ``fn(host)`` em paralelo (I/O de SSH é o gargalo)."""
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


# --- commands --------------------------------------------------------------

@app.command()
def hosts() -> None:
    """Lista os hosts configurados (sem contatá-los)."""
    config = _load_config()
    table = Table(title="Hosts configurados", title_style="bold cyan", expand=False)
    table.add_column("host", style="bold")
    table.add_column("ssh", style="cyan")
    table.add_column("status cmd", style="dim")
    table.add_column("provedor")
    table.add_column("expira")
    for h in config.hosts.values():
        s = h.server
        table.add_row(
            h.display,
            h.ssh,
            h.status_command or "—",
            s.provider or "—",
            s.expires.isoformat() if s.expires else "—",
        )
    console.print(table)
    console.print(f"[dim]fonte: {config.source or config_path()}[/dim]")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Sobrescreve config existente."),
) -> None:
    """Cria um arquivo de configuração inicial em ~/.config/vordr/config.toml."""
    path = config_path()
    if path.exists() and not force:
        err_console.print(
            f"[yellow]já existe:[/] {path}\nUse [bold]--force[/] para sobrescrever."
        )
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    console.print(f"[green]✔[/] configuração criada em [bold]{path}[/]")
    console.print("[dim]edite as datas de cobrança e rode `vordr cost`.[/dim]")


def _build_status_table(
    config: Config, metrics: dict[str, SystemMetrics], today: date
) -> Table:
    table = Table(title="Vordr · status dos servidores", title_style="bold cyan")
    table.add_column("host", style="bold")
    table.add_column("estado")
    table.add_column("uptime")
    table.add_column("load")
    table.add_column("ram")
    table.add_column("disco")
    table.add_column("docker")
    table.add_column("expira")

    for name, host in config.hosts.items():
        m = metrics[name]
        days = host.server.days_left(today)

        if not m.reachable:
            table.add_row(
                host.display,
                _state_text(False, m.error),
                Text(m.error or "inacessível", style="red"),
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
            host.display,
            _state_text(True, None),
            human_uptime(m.uptime_seconds),
            load_txt,
            ram_txt,
            disk_txt,
            docker_txt,
            Text(days_left_label(days), style=days_left_style(
                days, warn=config.warn_days, critical=config.critical_days)),
        )
    return table


@app.command()
def status(
    host: str = typer.Argument(None, help="Host específico (padrão: todos)."),
    raw: bool = typer.Option(
        False, "--raw", help="Mostra a saída nativa do status_command do host."
    ),
    watch: float = typer.Option(
        0, "--watch", "-w", help="Atualiza a cada N segundos (0 = uma vez)."
    ),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="Timeout SSH por host (s)."),
) -> None:
    """Painel de status: estado, uptime, carga, RAM, disco, containers e expiração."""
    config = _load_config()
    selected = _select_hosts(config, host)

    if raw:
        for h in selected:
            if not h.status_command:
                err_console.print(f"[yellow]{h.display}: sem status_command definido[/]")
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
    host: str = typer.Argument(None, help="Host específico (padrão: todos)."),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="Timeout SSH por host (s)."),
) -> None:
    """Detalhe de recursos: CPU/load, memória e disco com valores absolutos."""
    config = _load_config()
    selected = _select_hosts(config, host)
    metrics = _probe_all(selected, lambda a: probe_system(a, timeout=timeout))

    for h in selected:
        m: SystemMetrics = metrics[h.name]  # type: ignore[assignment]
        if not m.reachable:
            console.print(Panel(
                Text(m.error or "inacessível", style="red"),
                title=f"[bold]{h.display}[/] [red]offline[/]",
                border_style="red",
            ))
            continue

        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("k", style="dim")
        table.add_column("v")
        table.add_row("SO", m.os or "—")
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
                "memória",
                Text(
                    f"{human_kb(used)} / {human_kb(m.mem_total_kb)} ({m.mem_used_pct}%)",
                    style=pct_style(m.mem_used_pct),
                ),
            )
        if m.disk_total_kb:
            table.add_row(
                "disco /",
                Text(
                    f"{human_kb(m.disk_used_kb)} / {human_kb(m.disk_total_kb)} "
                    f"({m.disk_pct}%)",
                    style=pct_style(m.disk_pct),
                ),
            )
        if m.docker_running is not None:
            table.add_row("docker", f"{m.docker_running} rodando / {m.docker_total} total")
        table.add_row("sessões", str(m.users) if m.users is not None else "—")

        console.print(Panel(table, title=f"[bold cyan]{h.display}[/]", border_style="cyan"))


@app.command()
def security(
    host: str = typer.Argument(None, help="Host específico (padrão: todos)."),
    timeout: int = typer.Option(ssh.DEFAULT_TIMEOUT, help="Timeout SSH por host (s)."),
) -> None:
    """Auditoria de segurança: logins, falhas, portas, fail2ban e atualizações."""
    config = _load_config()
    selected = _select_hosts(config, host)
    metrics = _probe_all(selected, lambda a: probe_security(a, timeout=timeout))

    for h in selected:
        s: SecurityMetrics = metrics[h.name]  # type: ignore[assignment]
        if not s.reachable:
            console.print(Panel(
                Text(s.error or "inacessível", style="red"),
                title=f"[bold]{h.display}[/] [red]offline[/]",
                border_style="red",
            ))
            continue

        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("k", style="dim")
        table.add_column("v")

        fail_style = "green" if not s.failed_logins else (
            "bold red" if s.failed_logins > 50 else "yellow")
        table.add_row("sessões ativas", str(s.users_now) if s.users_now is not None else "—")
        table.add_row(
            "falhas de login",
            Text(str(s.failed_logins) if s.failed_logins is not None else "—",
                 style=fail_style),
        )
        if s.ports:
            ports = " ".join(str(p) for p in s.ports)
            table.add_row("portas LISTEN", ports)
        table.add_row("fail2ban", s.fail2ban or Text("não detectado", style="yellow"))
        if s.updates is not None:
            up_style = "green" if s.updates == 0 else "yellow"
            table.add_row("atualizações", Text(str(s.updates), style=up_style))
        if s.reboot_required:
            table.add_row("reboot", Text("necessário", style="bold red"))
        if s.last_logins:
            table.add_row("últimos logins", "\n".join(s.last_logins))

        # veredito simples
        warnings = []
        if s.failed_logins and s.failed_logins > 50:
            warnings.append("muitas falhas de login")
        if s.reboot_required:
            warnings.append("reboot pendente")
        if s.updates and s.updates > 0:
            warnings.append(f"{s.updates} atualizações")
        verdict = (
            Text("⚠ atenção: " + ", ".join(warnings), style="yellow")
            if warnings
            else Text("✔ sem alertas", style="green")
        )

        border = "yellow" if warnings else "green"
        console.print(Panel(table, title=f"[bold cyan]{h.display}[/]  {verdict}",
                            border_style=border))


def _monthly_by_currency(host: Host) -> dict[str, float]:
    """Soma o custo mensal de servidor + domínio, agrupado por moeda."""
    totals: dict[str, float] = {}
    for sub in (host.server, host.domain):
        if sub is None:
            continue
        monthly = sub.monthly_cost
        if monthly is not None:
            totals[sub.currency] = round(totals.get(sub.currency, 0.0) + monthly, 2)
    return totals


def _money(totals: dict[str, float]) -> str:
    if not totals:
        return "—"
    return " + ".join(f"{cur} {val:.2f}" for cur, val in sorted(totals.items()))


def _renewal_cell(
    expires: date | None, has_data: bool, config: Config, today: date
) -> Text:
    """Célula 'faltam Xd  AAAA-MM-DD' colorida por limiar (ou '—')."""
    if expires is None and not has_data:
        return Text("—", style="dim")
    days = (expires - today).days if expires else None
    suffix = f"  {expires.isoformat()}" if expires else ""
    return Text(
        days_left_label(days) + suffix,
        style=days_left_style(days, warn=config.warn_days, critical=config.critical_days),
    )


def _resolve_domain_expiry(dom: Subscription | None, *, offline: bool, timeout: int) -> date | None:
    """Expiração efetiva do domínio: o que está no config vence; senão, RDAP."""
    if dom is None:
        return None
    if dom.expires is not None:
        return dom.expires
    if dom.name and not offline:
        return rdap.domain_expiry(dom.name, timeout=timeout)
    return None


def _resolve_domain_expiries(
    hosts: list[Host], *, offline: bool, timeout: int
) -> dict[str, date | None]:
    """Resolve a expiração de domínio de vários hosts (RDAP em paralelo)."""
    resolved: dict[str, date | None] = {}
    pending: list[Host] = []
    for h in hosts:
        if h.domain is not None and h.domain.expires is not None:
            resolved[h.name] = h.domain.expires
        elif h.domain is not None and h.domain.name and not offline:
            resolved[h.name] = None  # placeholder; será preenchido pelo RDAP
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


def _cost_table(
    hosts: list[Host], config: Config, today: date, dom_expiries: dict[str, date | None]
) -> Table:
    table = Table(title="Vordr · custo & ciclo de vida", title_style="bold cyan")
    table.add_column("host", style="bold")
    table.add_column("provedor")
    table.add_column("hospedando há")
    table.add_column("servidor")
    table.add_column("domínio")
    table.add_column("custo/mês", justify="right")
    for host in hosts:
        dom = host.domain
        dom_has = dom is not None and (dom.has_data or bool(dom.name))
        table.add_row(
            host.display,
            host.server.provider or "—",
            human_age(host.server.age_days(today)),
            _renewal_cell(host.server.expires, host.server.has_data, config, today),
            _renewal_cell(dom_expiries.get(host.name), dom_has, config, today),
            _money(_monthly_by_currency(host)),
        )
    return table


def _cost_panel(host: Host, config: Config, today: date, dom_expiry: date | None) -> Panel:
    srv, dom = host.server, host.domain
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("k", style="dim")
    table.add_column("v")

    table.add_row("provedor", srv.provider or "—")
    age = human_age(srv.age_days(today))
    since = f"  (desde {srv.since.isoformat()})" if srv.since else ""
    table.add_row("hospedando há", f"{age}{since}" if age != "—" else "—")

    table.add_row("servidor renova", _renewal_cell(srv.expires, srv.has_data, config, today))
    if srv.cost is not None:
        table.add_row("", Text(f"{srv.currency} {srv.cost:.2f} / {srv.cycle}", style="dim"))

    if dom is not None and (dom_expiry is not None or dom.has_data or dom.name):
        cell = _renewal_cell(dom_expiry, dom.has_data or bool(dom.name), config, today)
        if dom.expires is None and dom_expiry is not None:
            cell.append("  (RDAP)", style="dim italic")
        table.add_row("domínio expira", cell)
        detail = " · ".join(p for p in (dom.name, dom.provider) if p)
        if detail:
            table.add_row("", Text(detail, style="dim"))
        if dom.cost is not None:
            table.add_row("", Text(f"{dom.currency} {dom.cost:.2f} / {dom.cycle}", style="dim"))
    else:
        table.add_row("domínio", Text("não configurado", style="dim"))

    table.add_row("custo/mês", Text(_money(_monthly_by_currency(host)), style="bold"))
    return Panel(table, title=f"[bold cyan]{host.display}[/]", border_style="cyan")


@app.command()
def cost(
    host: str = typer.Argument(
        None, help="Host específico → painel detalhado (padrão: tabela de todos)."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Não consultar RDAP; usa só o que está no config."
    ),
    timeout: int = typer.Option(
        rdap.DEFAULT_TIMEOUT, help="Timeout das consultas RDAP de domínio (s)."
    ),
) -> None:
    """Custo & ciclo de vida: hospedagem, renovação do servidor e do domínio.

    A expiração do domínio é buscada automaticamente via RDAP quando você informa
    apenas o ``name`` (sem ``expires``) no config. Use ``--offline`` para pular a rede.
    """
    config = _load_config()
    selected = _select_hosts(config, host)
    today = date.today()

    if host:
        dom_expiry = _resolve_domain_expiry(selected[0].domain, offline=offline, timeout=timeout)
        console.print(_cost_panel(selected[0], config, today, dom_expiry))
        return

    expiries = _resolve_domain_expiries(selected, offline=offline, timeout=timeout)
    console.print(_cost_table(selected, config, today, expiries))

    totals: dict[str, float] = {}
    missing: list[str] = []
    for h in selected:
        for cur, val in _monthly_by_currency(h).items():
            totals[cur] = round(totals.get(cur, 0.0) + val, 2)
        has_any = (
            h.server.has_data
            or (h.domain is not None and h.domain.has_data)
            or expiries.get(h.name) is not None
        )
        if not has_any:
            missing.append(h.display)

    if totals:
        console.print(f"[bold]total mensal estimado:[/] {_money(totals)}")

    if missing:
        console.print(
            f"[dim]sem dados de cobrança: {', '.join(missing)} — "
            f"edite {config.source or config_path()} (ou rode `vordr init`).[/dim]"
        )


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"vordr {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Mostra a versão e sai.",
    ),
) -> None:
    """Vordr monta guarda diante dos seus servidores."""


if __name__ == "__main__":  # pragma: no cover
    app()
