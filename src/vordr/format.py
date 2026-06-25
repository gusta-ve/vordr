"""Pure formatting and threshold-classification helpers.

Kept separate from the UI so they're trivially testable (no rich, no SSH).
"""

from __future__ import annotations


def human_uptime(seconds: int | None) -> str:
    """Format uptime seconds as ``2w 5d 3h``."""
    if seconds is None or seconds < 0:
        return "—"
    weeks, rem = divmod(seconds, 604800)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if weeks:
        parts.append(f"{weeks}w")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not parts:  # short uptime: show minutes
        parts.append(f"{minutes}m")
    return " ".join(parts[:3])


def human_age(days: int | None) -> str:
    """Format a span in days as ``1y 3mo`` (hosting/domain age)."""
    if days is None or days < 0:
        return "—"
    years, rem = divmod(days, 365)
    months = rem // 30
    parts = []
    if years:
        parts.append(f"{years}y")
    if months:
        parts.append(f"{months}mo")
    if not parts:  # less than a month: show days
        parts.append(f"{days}d")
    return " ".join(parts)


def human_kb(kilobytes: int | None) -> str:
    """Format KiB as a readable string (MiB/GiB/TiB)."""
    if kilobytes is None:
        return "—"
    value = float(kilobytes)
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f}{unit}" if unit == "KB" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def pct_style(pct: int | None, *, warn: int = 75, crit: int = 90) -> str:
    """Rich color for a usage percentage (green/yellow/red)."""
    if pct is None:
        return "dim"
    if pct >= crit:
        return "bold red"
    if pct >= warn:
        return "yellow"
    return "green"


def load_style(load_per_cpu: float | None) -> str:
    """Rich color for the per-CPU normalized load."""
    if load_per_cpu is None:
        return "dim"
    if load_per_cpu >= 1.0:
        return "bold red"
    if load_per_cpu >= 0.7:
        return "yellow"
    return "green"


def days_left_style(days: int | None, *, warn: int, critical: int) -> str:
    """Rich color for days left until expiry/charge."""
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
        return f"{abs(days)}d overdue"
    if days == 0:
        return "due today"
    return f"{days}d"
