"""Funções puras de formatação e classificação por limiar.

Mantidas separadas da UI para serem trivialmente testáveis (sem rich, sem SSH).
"""

from __future__ import annotations


def human_uptime(seconds: int | None) -> str:
    """Formata segundos de uptime como ``2sem 5d 3h``."""
    if seconds is None or seconds < 0:
        return "—"
    weeks, rem = divmod(seconds, 604800)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if weeks:
        parts.append(f"{weeks}sem")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not parts:  # uptime curto: mostra minutos
        parts.append(f"{minutes}min")
    return " ".join(parts[:3])


def human_kb(kilobytes: int | None) -> str:
    """Formata KiB como string legível (MiB/GiB/TiB)."""
    if kilobytes is None:
        return "—"
    value = float(kilobytes)
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f}{unit}" if unit == "KB" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def pct_style(pct: int | None, *, warn: int = 75, crit: int = 90) -> str:
    """Cor rich para um percentual de uso (verde/amarelo/vermelho)."""
    if pct is None:
        return "dim"
    if pct >= crit:
        return "bold red"
    if pct >= warn:
        return "yellow"
    return "green"


def load_style(load_per_cpu: float | None) -> str:
    """Cor rich para a carga normalizada por CPU."""
    if load_per_cpu is None:
        return "dim"
    if load_per_cpu >= 1.0:
        return "bold red"
    if load_per_cpu >= 0.7:
        return "yellow"
    return "green"


def days_left_style(days: int | None, *, warn: int, critical: int) -> str:
    """Cor rich para dias restantes até expiração/cobrança."""
    if days is None:
        return "dim"
    if days < 0:
        return "bold red"
    if days <= critical:
        return "bold red"
    if days <= warn:
        return "yellow"
    return "green"


def days_left_label(days: int | None) -> str:
    if days is None:
        return "—"
    if days < 0:
        return f"vencido há {abs(days)}d"
    if days == 0:
        return "vence hoje"
    return f"{days}d"
