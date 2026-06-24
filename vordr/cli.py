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

from . import __version__, ssh
from .config import Config, ConfigError, Host, config_path, load
from .format import (
    days_left_label,
    days_left_style,
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
# quando o provedor vai cobrar de novo).

[thresholds]
warn_days = 14       # avisa (amarelo) quando faltar <= esta qtd de dias
critical_days = 7    # alerta (vermelho) quando faltar <= esta qtd de dias

[hosts.web]
ssh = "web"                   # alias no ~/.ssh/config
label = "Web"
# status_command = "meu-status"   # opcional: seu script p/ `vordr status --raw`

  [hosts.web.billing]
  provider = "Hetzner"
  expires = "2026-08-15"      # AAAA-MM-DD — próxima renovação/expiração
  cost = 6.99
  currency = "USD"
  cycle = "monthly"           # monthly | yearly

[hosts.db]
ssh = "db"
label = "DB"

  [hosts.db.billing]
  provider = "DigitalOcean"
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
        b = h.billing
        table.add_row(
            h.display,
            h.ssh,
            h.status_command or "—",
            b.provider or "—",
            b.expires.isoformat() if b.expires else "—",
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
        billing = host.billing
        days = billing.days_left(today)

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


@app.command()
def cost(
    timeout: int = typer.Option(0, hidden=True),  # cost não faz SSH
) -> None:
    """Custo e expiração: dias até a próxima cobrança e gasto mensal estimado."""
    config = _load_config()
    today = date.today()

    table = Table(title="Vordr · custo & expiração", title_style="bold cyan")
    table.add_column("host", style="bold")
    table.add_column("provedor")
    table.add_column("expira em")
    table.add_column("data")
    table.add_column("ciclo")
    table.add_column("custo/mês", justify="right")

    total_monthly = 0.0
    totals_by_currency: dict[str, float] = {}
    missing: list[str] = []

    for host in config.hosts.values():
        b = host.billing
        days = b.days_left(today)
        if b.expires is None and b.cost is None:
            missing.append(host.display)
        monthly = b.monthly_cost
        if monthly is not None:
            totals_by_currency[b.currency] = totals_by_currency.get(b.currency, 0.0) + monthly
            total_monthly += monthly

        cost_txt = f"{b.currency} {monthly:.2f}" if monthly is not None else "—"
        table.add_row(
            host.display,
            b.provider or "—",
            Text(days_left_label(days),
                 style=days_left_style(days, warn=config.warn_days,
                                       critical=config.critical_days)),
            b.expires.isoformat() if b.expires else "—",
            b.cycle,
            cost_txt,
        )

    console.print(table)

    if totals_by_currency:
        parts = [f"{cur} {val:.2f}" for cur, val in sorted(totals_by_currency.items())]
        console.print(f"[bold]total mensal estimado:[/] {' + '.join(parts)}")

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
