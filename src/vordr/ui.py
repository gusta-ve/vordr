"""Vordr's console look — palette, accents and minimal table/card styles.

Steel theme: a sober silver-gunmetal accent on a dark terminal, matching the sibling
tools' design language (a per-tool true-color accent) while staying minimal — no heavy
boxes, generous whitespace, ``·`` separators.
"""

from __future__ import annotations

from rich.box import SIMPLE_HEAD
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

# --- palette (steel) -------------------------------------------------------
ACCENT = "#9cb4d6"        # silver-gunmetal — the signature
ACCENT_SOFT = "#6c7f9c"   # dimmer accent for rules/separators
MUTED = "#6e7681"         # secondary text
OK = "green"
WARN = "yellow"
CRIT = "bold red"

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


def brand(sub: str = "", *, accent: str = ACCENT) -> Text:
    """The ``vordr · <sub>`` title line."""
    t = Text()
    t.append("vordr", style=f"bold {accent}")
    if sub:
        t.append("  ·  ", style=MUTED)
        t.append(sub, style=f"bold {accent}")
    return t


def indent(renderable: RenderableType, pad: int = 2) -> Padding:
    return Padding(renderable, (0, 0, 0, pad))


def grid(*headers: str, right: tuple[str, ...] = ()) -> Table:
    """A minimal table: accent header, a single rule beneath it, no frame."""
    table = Table(
        box=SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        padding=(0, 2),
        header_style=f"bold {ACCENT}",
        border_style=ACCENT_SOFT,
    )
    for h in headers:
        table.add_column(h, justify="right" if h in right else "left")
    return table


def kv() -> Table:
    """A frameless key/value table for cards (key muted, value default)."""
    table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2))
    table.add_column(style=MUTED, no_wrap=True)
    table.add_column()
    return table


def card(title: RenderableType, body: RenderableType) -> Group:
    """A frameless card: a brand-style title and an indented body."""
    return Group(indent(title), indent(body), Text())


def meta(*parts: str) -> Text:
    """A dim ``a  ·  b  ·  c`` footer line."""
    t = Text(style=MUTED)
    for i, part in enumerate(parts):
        if i:
            t.append("  ·  ", style=ACCENT_SOFT)
        t.append(part)
    return t
