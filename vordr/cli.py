"""Interface de linha de comando do Vordr."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
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
  provider = "Hetzner"        # com token (vordr secret set hetzner), since/custo
  # provider_server = "web-01"  # nome do servidor na API, se != do alias
  since   = "2024-03-01"      # vêm da API; o que você puser aqui sempre vence.
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


def _require_ssh(selected: list[Host]) -> list[Host]:
    """Mantém só hosts com alias SSH; avisa sobre os 'billing-only' (sem SSH)."""
    usable = [h for h in selected if h.ssh.strip()]
    skipped = [h.display for h in selected if not h.ssh.strip()]
    if skipped:
        console.print(
            f"[dim]sem alias SSH (use `vordr cost`/`billing`): {', '.join(skipped)}[/]"
        )
    return usable


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


def _is_interactive() -> bool:
    """Há um terminal de verdade para fazer perguntas? (falso em pipes/testes)."""
    return sys.stdin.isatty()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Sobrescreve config existente."),
) -> None:
    """Cria o config. Num terminal, vira um assistente que importa seus servidores.

    Com um token salvo, o ``init`` lista os servidores da conta e monta o config para
    você — sem escrever TOML na mão. Sem terminal (pipe/CI) ou sem token, escreve um
    modelo comentado.
    """
    path = config_path()
    interactive = _is_interactive()
    if path.exists() and not force:
        overwrite = interactive and typer.confirm(f"{path} já existe. Sobrescrever?", default=False)
        if not overwrite:
            err_console.print(
                f"[yellow]já existe:[/] {path}\nUse [bold]--force[/] para sobrescrever."
            )
            raise typer.Exit(1)

    blocks = _wizard_import() if interactive else []
    content = _render_config(blocks) if blocks else CONFIG_TEMPLATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    console.print(f"[green]✔[/] configuração criada em [bold]{path}[/]")
    if blocks:
        console.print(
            f"[dim]{len(blocks)} host(s) importado(s). Rode `vordr cost` ou `vordr status`.[/dim]"
        )
    else:
        console.print(
            "[dim]edite os hosts (ou rode `vordr secret set` e `vordr init` de novo "
            "para importar da API) e use `vordr cost`.[/dim]"
        )


def _suggest_alias(name: str, aliases: list[str]) -> str | None:
    """Casa o nome do servidor com um alias SSH (igualdade ou substring)."""
    low = name.lower()
    for alias in aliases:
        al = alias.lower()
        if al == low or al in low or low in al:
            return alias
    return None


def _toml_key(value: str, used: set[str]) -> str:
    """Chave de tabela TOML segura e única (A-Za-z0-9_-)."""
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
        ssh_line = 'ssh = ""   # sem alias SSH: entra em cost/billing, não em status'
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
        lines.append("  # preço fixo (vence a API). Apague para voltar ao valor da API.")
    else:
        lines.append("  # custo e since vêm da API automaticamente (preço de lista).")
    return "\n".join(lines)


def _render_config(blocks: list[str]) -> str:
    header = (
        "# Configuração do Vordr — gerada por `vordr init`.\n"
        "# Campos em branco são preenchidos pela API/RDAP; o que você escrever vence.\n\n"
        "[thresholds]\n"
        "warn_days = 14\n"
        "critical_days = 7\n\n"
    )
    return header + "\n\n".join(blocks) + "\n"


def _wizard_import() -> list[str]:
    """Assistente interativo: descobre servidores pela API e monta blocos de config."""
    tokened = [p for p in _PROVIDER_CLIENTS if secrets.get_token(p)]
    if not tokened:
        console.print("[dim]Nenhum token de provedor salvo.[/]")
        choice = typer.prompt(
            f"Configurar um agora? Provedor ({'/'.join(secrets.ENV_VARS)}) ou enter p/ pular",
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
        console.print("[yellow]Nenhum servidor encontrado nas contas.[/]")
        return []
    console.print(f"[cyan]{total} servidor(es) encontrado(s).[/] Mapeie cada um:")

    aliases = ssh.list_aliases()
    blocks: list[str] = []
    used: set[str] = set()
    for prov in sorted(discovered):
        for name, sb in sorted(discovered[prov].items()):
            if not typer.confirm(f"  importar '{name}' ({prov.capitalize()})?", default=True):
                continue
            suggestion = _suggest_alias(name, aliases)
            if suggestion:
                alias = typer.prompt(
                    "    alias SSH (p/ status/resources)", default=suggestion
                ).strip()
            else:
                alias = typer.prompt(
                    "    alias SSH (enter se não houver — entra só em cost/billing)",
                    default="",
                    show_default=False,
                ).strip()
            api_hint = (
                f"{sb.currency} {sb.cost_gross:.2f}"
                if sb.cost_gross is not None
                else "desconhecido"
            )
            cost_in = typer.prompt(
                f"    preço/mês fixo? (enter = usar a API: {api_hint})",
                default="",
                show_default=False,
            ).strip()
            cost: float | None = None
            if cost_in:
                try:
                    cost = round(float(cost_in.replace(",", ".")), 2)
                except ValueError:
                    console.print("[yellow]    valor inválido — usando o da API.[/]")
            key = _toml_key(alias or name, used)
            blocks.append(_render_host_block(key, alias, prov.capitalize(), sb, cost))
    return blocks


secret_app = typer.Typer(
    help="Gerencia tokens de API de provedores — guardados fora do repositório.",
    no_args_is_help=True,
)
app.add_typer(secret_app, name="secret")


def _store_token_flow(provider: str) -> bool:
    """Pede, valida (com uma leitura na API) e grava o token. True se gravou."""
    token = typer.prompt(f"Token da API ({provider})", hide_input=True).strip()
    if not token:
        err_console.print("[red]token vazio.[/]")
        return False
    client = _PROVIDER_CLIENTS.get(provider)
    if client is not None:  # valida com uma leitura antes de gravar
        try:
            client.fetch_servers(token, timeout=15)
        except providers.ProviderError as exc:
            err_console.print(f"[red]token rejeitado:[/] {exc}")
            return False
    path = secrets.set_token(provider, token)
    console.print(f"[green]✔[/] token de [bold]{provider}[/] salvo em [bold]{path}[/] (chmod 600)")
    return True


@secret_app.command("set")
def secret_set(
    provider: str = typer.Argument(..., help=f"Um de: {', '.join(secrets.ENV_VARS)}."),
) -> None:
    """Salva (e valida) o token de API de um provedor em ~/.config/vordr/secrets.toml."""
    provider = provider.lower()
    if provider not in secrets.ENV_VARS:
        err_console.print(
            f"[red]provedor desconhecido:[/] {provider} "
            f"(conhecidos: {', '.join(secrets.ENV_VARS)})"
        )
        raise typer.Exit(2)
    if not _store_token_flow(provider):
        raise typer.Exit(1)
    console.print(
        f"[dim]a variável de ambiente {secrets.ENV_VARS[provider]} tem prioridade "
        f"sobre o arquivo, se definida.[/dim]"
    )


@secret_app.command("status")
def secret_status() -> None:
    """Mostra quais provedores têm token configurado (sem revelá-lo)."""
    table = Table(title="Tokens de API", title_style="bold cyan")
    table.add_column("provedor", style="bold")
    table.add_column("fonte")
    table.add_column("token")
    labels = {"env": None, "file": "arquivo"}
    for prov in sorted(secrets.ENV_VARS):
        src = secrets.token_source(prov)
        tok = secrets.get_token(prov)
        source = f"env ({secrets.ENV_VARS[prov]})" if src == "env" else labels.get(src) or "—"
        table.add_row(
            prov,
            source,
            secrets.mask(tok) if tok else Text("não configurado", style="dim"),
        )
    console.print(table)


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
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)

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
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)
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
    selected = _require_ssh(_select_hosts(config, host))
    if not selected:
        raise typer.Exit(0)
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


# --- ciclo de vida: resolve config (manual) > API do provedor > RDAP ----------

# provedores com cliente de API embutido. O valor MANUAL no config sempre vence
# o que vem daqui — é o "caminho alternativo" para preços promocionais/legados.
# Guardamos o *módulo* (não a função) para que `.fetch_servers` seja resolvido em
# tempo de chamada — testes conseguem fazer monkeypatch dele.
_PROVIDER_CLIENTS = {
    "hetzner": hetzner,
    "vultr": vultr,
}


@dataclass
class _Lifecycle:
    """Valores efetivos de um host após mesclar config, API do provedor e RDAP."""

    since: date | None = None
    since_auto: bool = False
    cost: float | None = None  # custo mensal do servidor (normalizado)
    cost_net: float | None = None  # net, quando difere do cobrado (via API)
    currency: str = "USD"
    cost_auto: bool = False
    domain_expiry: date | None = None
    domain_expiry_auto: bool = False


def _money(totals: dict[str, float]) -> str:
    if not totals:
        return "—"
    return " + ".join(f"{cur} {val:.2f}" for cur, val in sorted(totals.items()))


def _monthly_by_currency(host: Host, lc: _Lifecycle) -> dict[str, float]:
    """Custo mensal de servidor + domínio (servidor pode vir da API), por moeda."""
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
    """Célula 'faltam Xd  AAAA-MM-DD' colorida por limiar (ou '—')."""
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


def _referenced_providers(hosts: list[Host]) -> set[str]:
    """Provedores citados explicitamente pelos hosts do config."""
    return {
        h.server.provider.lower()
        for h in hosts
        if h.server.provider and h.server.provider.lower() in _PROVIDER_CLIENTS
    }


def _api_providers(hosts: list[Host]) -> list[str]:
    """Provedores a consultar: os referenciados no config + os que têm token salvo."""
    referenced = _referenced_providers(hosts)
    with_token = {p for p in _PROVIDER_CLIENTS if secrets.get_token(p)}
    return sorted(referenced | with_token)


def _fetch_provider_servers(
    hosts: list[Host], *, timeout: int, discover: bool = False
) -> tuple[dict[str, dict[str, providers.ServerBilling]], list[str]]:
    """Lista os servidores na API dos provedores. Devolve (dados, avisos).

    Com ``discover=True`` consulta também todo provedor que tenha token salvo (não só
    os citados no config) — é o que permite achar servidores sem nenhuma entrada no
    TOML. Sem token, só avisa para os provedores realmente referenciados por um host.
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
                    f"{prov}: sem token — rode `vordr secret set {prov}` para automatizar"
                )
            continue
        try:
            servers[prov] = _PROVIDER_CLIENTS[prov].fetch_servers(token, timeout=timeout)
        except providers.ProviderError as exc:
            notes.append(f"{prov}: {exc}")
    return servers, notes


def _discovered_host(prov: str, sb: providers.ServerBilling) -> Host:
    """Host sintético a partir de um servidor achado na API (sem entrada no config).

    Sem ``ssh`` (logo, fora de status/resources/security); custo e ``since`` fluem da
    API via :func:`_resolve_lifecycle`.
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
    """Une hosts do config (enriquecidos pela API) com servidores só achados na API."""
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
    """Acha a linha de um host por nome/label/alias SSH (config ou descoberto)."""
    low = name.lower()
    for host, lc in rows:
        if low in {host.name.lower(), (host.label or "").lower(), host.ssh.lower()}:
            return host, lc
    return None


def _match_server(
    host: Host, servers: dict[str, dict[str, providers.ServerBilling]]
) -> providers.ServerBilling | None:
    """Casa um host com seu servidor na API (por provider_server, alias, nome ou label)."""
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
    table = Table(title="Vordr · custo & ciclo de vida", title_style="bold cyan")
    table.add_column("host", style="bold")
    table.add_column("provedor")
    table.add_column("hospedando há")
    table.add_column("servidor")
    table.add_column("domínio")
    table.add_column("custo/mês", justify="right")
    for host, lc in rows:
        dom = host.domain
        dom_has = dom is not None and (dom.has_data or bool(dom.name))
        table.add_row(
            host.display,
            host.server.provider or "—",
            _age_text(lc, today),
            _renewal_cell(host.server.expires, host.server.has_data, config, today),
            _renewal_cell(lc.domain_expiry, dom_has, config, today),
            _money(_monthly_by_currency(host, lc)),
        )
    return table


def _cost_panel(host: Host, config: Config, today: date, lc: _Lifecycle) -> Panel:
    srv, dom = host.server, host.domain
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("k", style="dim")
    table.add_column("v")

    table.add_row("provedor", srv.provider or "—")
    age_line = Text(_age_text(lc, today))
    if lc.since:
        age_line.append(f"  (desde {lc.since.isoformat()})", style="dim")
        if lc.since_auto:
            age_line.append("  (API)", style="dim italic")
    table.add_row("hospedando há", age_line)

    table.add_row("servidor renova", _renewal_cell(srv.expires, srv.has_data, config, today))
    if lc.cost is not None:
        money = Text(f"{lc.currency} {lc.cost:.2f} / mês", style="dim")
        if lc.cost_auto:
            money.append("  (API)", style="dim italic")
        table.add_row("", money)
        if lc.cost_net is not None:
            table.add_row("", Text(f"líquido {lc.currency} {lc.cost_net:.2f}", style="dim"))

    if dom is not None and (lc.domain_expiry is not None or dom.has_data or dom.name):
        cell = _renewal_cell(lc.domain_expiry, dom.has_data or bool(dom.name), config, today)
        if lc.domain_expiry_auto:
            cell.append("  (RDAP)", style="dim italic")
        table.add_row("domínio expira", cell)
        detail = " · ".join(p for p in (dom.name, dom.provider) if p)
        if detail:
            table.add_row("", Text(detail, style="dim"))
        if dom.cost is not None:
            table.add_row("", Text(f"{dom.currency} {dom.cost:.2f} / {dom.cycle}", style="dim"))
    else:
        table.add_row("domínio", Text("não configurado", style="dim"))

    table.add_row("custo/mês", Text(_money(_monthly_by_currency(host, lc)), style="bold"))
    return Panel(table, title=f"[bold cyan]{host.display}[/]", border_style="cyan")


@app.command()
def cost(
    host: str = typer.Argument(
        None, help="Host específico → painel detalhado (padrão: tabela de todos)."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Não consultar rede (RDAP/API); usa só o config."
    ),
    timeout: int = typer.Option(
        rdap.DEFAULT_TIMEOUT, help="Timeout das consultas de rede — RDAP e API (s)."
    ),
) -> None:
    """Custo & ciclo de vida: hospedagem, renovação do servidor e do domínio.

    Com um token salvo, **descobre os servidores da conta** automaticamente — o config é
    opcional. Os valores do config sempre vencem; o que faltar vem da API (custo/``since``)
    e do RDAP (expiração do domínio). Use ``--offline`` para usar só o config, sem rede.
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
            "[yellow]Nada para mostrar.[/] Configure um token "
            "([bold]vordr secret set hetzner|vultr[/]) para descobrir os servidores "
            "pela API, ou [bold]vordr init[/] para declarar hosts via SSH."
        )
        for note in notes:
            console.print(f"[dim yellow]{note}[/]")
        raise typer.Exit(0)

    if host:
        row = _find_row(rows, host)
        if row is None:
            known = ", ".join(sorted(h.display for h, _ in rows)) or "(nenhum)"
            err_console.print(f"[bold red]host '{host}' não encontrado.[/] Conhecidos: {known}")
            raise typer.Exit(2)
        console.print(_cost_panel(row[0], config, today, row[1]))
    else:
        console.print(_cost_table(rows, config, today))

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

        if totals:
            console.print(f"[bold]total mensal estimado:[/] {_money(totals)}")
        if missing:
            console.print(
                f"[dim]sem dados de cobrança: {', '.join(missing)} — "
                f"edite {config.source or config_path()} (ou rode `vordr init`).[/dim]"
            )

    for prov in sorted(accounts):
        burn, _cur = _provider_monthly_burn(rows, prov)
        console.print(_billing_summary_line(prov, accounts[prov], burn, today))

    for note in notes:
        console.print(f"[dim yellow]{note}[/]")


# --- saldo & cobrança por provedor -------------------------------------------

def _billing_model(prov: str) -> str:
    """'prepaid' (crédito/saldo) ou 'postpaid' (cartão) — declarado pelo módulo."""
    return getattr(_PROVIDER_CLIENTS.get(prov), "BILLING_MODEL", "postpaid")


def _first_of_next_month(today: date) -> date:
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def _fetch_provider_accounts(
    hosts: list[Host], *, timeout: int
) -> tuple[dict[str, providers.AccountBilling], list[str]]:
    """Saldo das contas dos provedores referenciados que expõem ``fetch_account``."""
    accounts: dict[str, providers.AccountBilling] = {}
    notes: list[str] = []
    for prov in _api_providers(hosts):
        client = _PROVIDER_CLIENTS[prov]
        if not hasattr(client, "fetch_account"):
            continue  # provedor postpago — sem saldo via API
        token = secrets.get_token(prov)
        if not token:
            continue  # token faltando já é avisado pelo fetch de servidores
        try:
            accounts[prov] = client.fetch_account(token, timeout=timeout)
        except providers.ProviderError as exc:
            notes.append(f"{prov}: {exc}")
    return accounts, notes


def _provider_monthly_burn(
    rows: list[tuple[Host, _Lifecycle]], prov: str
) -> tuple[float | None, str | None]:
    """Soma o custo mensal dos hosts de um provedor (o 'burn' que consome o saldo)."""
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
    """Dias até o crédito esgotar, dado o consumo mensal."""
    if net_remaining is None or not monthly_burn or monthly_burn <= 0:
        return None, None
    daily = monthly_burn / 30.0
    days = int(net_remaining / daily)
    return days, today + timedelta(days=days)


def _billing_summary_line(
    prov: str, acct: providers.AccountBilling, burn: float | None, today: date
) -> str:
    """Linha curta para o rodapé do `cost` (crédito + runway)."""
    parts = [f"[bold]{prov.capitalize()}[/]"]
    cr = acct.credit
    if cr is not None:
        parts.append(f"crédito {acct.currency} {cr:.2f}")
    if acct.pending_charges:
        parts.append(f"pendente {acct.currency} {acct.pending_charges:.2f}")
    net = acct.net_remaining
    if net is not None:
        parts.append(f"líquido {acct.currency} {net:.2f}")
    days, runout = _runway(net, burn, today)
    if days is not None and runout is not None:
        parts.append(f"runway ~{days}d → {runout.isoformat()}")
    return "[dim]" + "  ·  ".join(parts) + "[/]"


def _billing_panel(
    prov: str,
    acct: providers.AccountBilling | None,
    burn: float | None,
    currency: str | None,
    config: Config,
    today: date,
    offline: bool,
) -> Panel:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("provedor", prov.capitalize())

    if _billing_model(prov) == "prepaid":
        table.add_row("modelo", "pré-pago (crédito/saldo)")
        if acct is None:
            if offline:
                detail = Text("— (modo offline)", style="dim")
            elif not secrets.get_token(prov):
                detail = Text(f"sem token — rode `vordr secret set {prov}`", style="yellow")
            else:
                detail = Text("indisponível", style="dim")
            table.add_row("saldo", detail)
        else:
            cr = acct.credit
            if cr is not None:
                table.add_row("crédito", f"{acct.currency} {cr:.2f}")
            if acct.pending_charges:
                table.add_row("pendente", f"{acct.currency} {acct.pending_charges:.2f}")
            net = acct.net_remaining
            if net is not None:
                table.add_row("líquido", Text(f"{acct.currency} {net:.2f}", style="bold"))
            days, runout = _runway(net, burn, today)
            if days is not None and runout is not None:
                style = days_left_style(days, warn=config.warn_days, critical=config.critical_days)
                table.add_row(
                    "runway",
                    Text(f"~{days} dias  (esgota {runout.isoformat()})", style=style),
                )
                table.add_row(
                    "cobrança", Text("via crédito — sem cartão até o saldo esgotar", style="dim")
                )
            else:
                table.add_row("cobrança", Text("via crédito", style="dim"))
    else:  # postpago — cobrado no cartão, calendário fixo
        table.add_row("modelo", "postpago (cartão)")
        nxt = _first_of_next_month(today)
        days = (nxt - today).days
        est = f"  (≈ {currency} {burn:.2f} / mês)" if burn is not None and currency else ""
        table.add_row(
            "próxima cobrança",
            Text(
                f"{nxt.isoformat()}  (em {days}d){est}",
                style=days_left_style(days, warn=config.warn_days, critical=config.critical_days),
            ),
        )
        table.add_row(
            "saldo", Text(f"— (não exposto pela API da {prov.capitalize()})", style="dim")
        )

    return Panel(table, title=f"[bold cyan]{prov.capitalize()}[/]", border_style="cyan")


@app.command()
def billing(
    offline: bool = typer.Option(
        False, "--offline", help="Não consultar a API; mostra só o modelo de cobrança."
    ),
    timeout: int = typer.Option(
        rdap.DEFAULT_TIMEOUT, help="Timeout das consultas à API do provedor (s)."
    ),
) -> None:
    """Saldo, crédito e próxima cobrança de cada provedor.

    Para provedores pré-pagos (ex.: Vultr) mostra crédito, uso pendente e o
    *runway* — quando o saldo esgota e a cobrança no cartão começa. Para postpagos
    (ex.: Hetzner) mostra a próxima data de cobrança e o custo estimado.
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
            "[yellow]Nenhum provedor de API para mostrar.[/] Configure um token "
            '([bold]vordr secret set hetzner|vultr[/]) ou defina provider = "Hetzner"/"Vultr".'
        )
        for note in notes:
            console.print(f"[dim yellow]{note}[/]")
        raise typer.Exit(0)

    for prov in providers_seen:
        burn, currency = _provider_monthly_burn(rows, prov)
        console.print(
            _billing_panel(prov, accounts.get(prov), burn, currency, config, today, offline)
        )

    for note in notes:
        console.print(f"[dim yellow]{note}[/]")


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
