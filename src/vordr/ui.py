"""Vordr's console look — palette, accents and minimal table/card styles.

Steel theme: a sober silver-gunmetal accent on a dark terminal, matching the sibling
tools' design language while staying minimal — no heavy boxes, generous whitespace,
``·`` separators.

Dependency-free: this is a tiny stdlib re-implementation of the slice of a rich-style
console that Vordr uses (styled ``Text``, frameless ``Table``, ``Group``, indentation,
``[tag]…[/]`` markup and a full-screen ``Live`` view). Colour is emitted as ANSI and is
switched off automatically when stdout isn't a TTY or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Union

# --- palette (steel) -------------------------------------------------------
ACCENT = "#9cb4d6"        # silver-gunmetal — the signature
ACCENT_SOFT = "#6c7f9c"   # dimmer accent for rules/separators
MUTED = "#6e7681"         # secondary text
OK = "green"
WARN = "yellow"
CRIT = "bold red"

_ATTRS = {"bold": 1, "dim": 2, "italic": 3, "underline": 4}
_COLORS = {"black": 30, "red": 31, "green": 32, "yellow": 33,
           "blue": 34, "magenta": 35, "cyan": 36, "white": 37}


def _sgr(style: str | None) -> str:
    """Turn a style string (``"bold red"``, ``"#9cb4d6"``, ``"dim"``) into an SGR prefix."""
    if not style:
        return ""
    codes: list[str] = []
    for tok in style.split():
        if tok in _ATTRS:
            codes.append(str(_ATTRS[tok]))
        elif tok in _COLORS:
            codes.append(str(_COLORS[tok]))
        elif tok.startswith("#") and len(tok) == 7:
            r, g, b = (int(tok[i:i + 2], 16) for i in (1, 3, 5))
            codes.append(f"38;2;{r};{g};{b}")
    return f"\x1b[{';'.join(codes)}m" if codes else ""


def _known_style(name: str) -> bool:
    """Whether every token in a markup tag is a style we understand (else it's literal)."""
    toks = name.split()
    return bool(toks) and all(t in _ATTRS or t in _COLORS or t.startswith("#") for t in toks)


class Text:
    """A run of styled spans; the atom the console prints."""

    def __init__(self, text: str = "", style: str | None = None) -> None:
        self.spans: list[tuple[str, str | None]] = []
        if text:
            self.spans.append((text, style))

    def append(self, text: str, style: str | None = None) -> Text:
        if text:
            self.spans.append((text, style))
        return self

    @property
    def plain(self) -> str:
        return "".join(t for t, _ in self.spans)

    def render(self, width: int = 0, color: bool = True) -> str:
        if not color:
            return self.plain
        out = []
        for txt, style in self.spans:
            sgr = _sgr(style)
            out.append(f"{sgr}{txt}\x1b[0m" if sgr else txt)
        return "".join(out)


Renderable = Union[str, Text, "Table", "Group", "Indent"]


def _parse_markup(s: str) -> Text:
    """Parse ``[style]…[/]`` / ``[/style]`` markup into a Text (unknown tags stay literal)."""
    t = Text()
    stack: list[str | None] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "[" and "]" in s[i:]:
            close = s.index("]", i)
            tag = s[i + 1:close]
            if tag.startswith("/"):                       # closing tag
                if stack:
                    stack.pop()
                    i = close + 1
                    continue
            elif _known_style(tag):                        # opening style tag
                stack.append(tag)
                i = close + 1
                continue
            # not a style tag — emit the '[' literally and move on
        t.append(ch, stack[-1] if stack else None)
        i += 1
    return t


def _plain(cell: Renderable) -> str:
    if isinstance(cell, Text):
        return cell.plain
    return str(cell)


def _render(cell: Renderable, color: bool) -> str:
    if isinstance(cell, str):
        return _parse_markup(cell).render(color=color)
    return cell.render(color=color)


class Table:
    """A minimal, frameless table. ``header=True`` adds an accent header + a rule."""

    def __init__(self, *, header: bool = True, gap: int = 2) -> None:
        self.header = header
        self.gap = gap
        self.cols: list[dict] = []
        self.rows: list[list[Renderable]] = []

    def add_column(self, label: str = "", *, justify: str = "left",
                   style: str | None = None) -> None:
        self.cols.append({"label": label, "justify": justify, "style": style})

    def add_row(self, *cells: Renderable) -> None:
        self.rows.append(list(cells))

    def render(self, width: int = 0, color: bool = True) -> str:
        n = len(self.cols)
        widths = [len(_plain(c["label"])) if self.header else 0 for c in self.cols]
        for row in self.rows:
            for i in range(n):
                cell = row[i] if i < len(row) else ""
                for line in _plain(cell).split("\n"):
                    widths[i] = max(widths[i], len(line))
        pad = " " * self.gap

        def fmt(cell: Renderable, i: int) -> str:
            w = widths[i]
            plain = _plain(cell)
            fill = " " * max(0, w - len(plain))
            body = _render(cell, color)
            return (fill + body) if self.cols[i]["justify"] == "right" else (body + fill)

        lines: list[str] = []
        if self.header:
            head = Text()
            for i, c in enumerate(self.cols):
                if i:
                    head.append(pad)
                label = c["label"]
                w = widths[i]
                cell = label + " " * max(0, w - len(label))
                head.append(cell, f"bold {ACCENT}")
            lines.append(head.render(color=color))
            rule = "─" * (sum(widths) + self.gap * (n - 1))
            lines.append(Text(rule, ACCENT_SOFT).render(color=color))
        for row in self.rows:
            # multi-line cells (e.g. a list of logins) expand downward
            height = max((_plain(row[i] if i < len(row) else "").count("\n") + 1
                          for i in range(n)), default=1)
            split = [[_plain(row[i] if i < len(row) else "")][0].split("\n") for i in range(n)]
            for ln in range(height):
                parts = []
                for i in range(n):
                    piece = split[i][ln] if ln < len(split[i]) else ""
                    style = self.cols[i]["style"]
                    # re-wrap plain sub-line, honouring a per-cell Text style if present
                    cell = row[i] if i < len(row) else ""
                    if isinstance(cell, Text) and height == 1:
                        parts.append(fmt(cell, i))
                    else:
                        w = widths[i]
                        fill = " " * max(0, w - len(piece))
                        rendered = _render(Text(piece, style) if style else piece, color)
                        parts.append((fill + rendered) if self.cols[i]["justify"] == "right"
                                     else (rendered + fill))
                lines.append(pad.join(parts).rstrip())
        return "\n".join(lines)


class Group:
    """A vertical stack of renderables."""

    def __init__(self, *items: Renderable) -> None:
        self.items = list(items)

    def render(self, width: int = 0, color: bool = True) -> str:
        return "\n".join(_render(it, color) for it in self.items)


class Indent:
    """Left-pad every line of a renderable."""

    def __init__(self, inner: Renderable, pad: int = 2) -> None:
        self.inner = inner
        self.pad = pad

    def render(self, width: int = 0, color: bool = True) -> str:
        prefix = " " * self.pad
        body = _render(self.inner, color)
        return "\n".join(prefix + line for line in body.split("\n"))


# --- builders (same API as before) -----------------------------------------

def brand(sub: str = "", *, accent: str = ACCENT) -> Text:
    """The ``vordr · <sub>`` title line."""
    t = Text("vordr", f"bold {accent}")
    if sub:
        t.append("  ·  ", MUTED)
        t.append(sub, f"bold {accent}")
    return t


def indent(renderable: Renderable, pad: int = 2) -> Indent:
    return Indent(renderable, pad)


def grid(*headers: str, right: tuple[str, ...] = ()) -> Table:
    """A minimal table: accent header, a single rule beneath it, no frame."""
    table = Table(header=True)
    for h in headers:
        table.add_column(h, justify="right" if h in right else "left")
    return table


def kv() -> Table:
    """A frameless key/value table for cards (key muted, value default)."""
    table = Table(header=False)
    table.add_column(style=MUTED)
    table.add_column()
    return table


def card(title: Renderable, body: Renderable) -> Group:
    """A frameless card: a brand-style title and an indented body."""
    return Group(indent(title), indent(body), Text())


def meta(*parts: str) -> Text:
    """A dim ``a  ·  b  ·  c`` footer line."""
    t = Text()
    for i, part in enumerate(parts):
        if i:
            t.append("  ·  ", ACCENT_SOFT)
        t.append(part, MUTED)
    return t


# --- console ----------------------------------------------------------------

class Console:
    """Prints renderables/markup to a stream, with ANSI colour when the stream is a TTY."""

    def __init__(self, *, stderr: bool = False) -> None:
        self._stderr = stderr

    @property
    def file(self):
        return sys.stderr if self._stderr else sys.stdout

    @property
    def width(self) -> int:
        env = os.environ.get("COLUMNS")
        if env and env.isdigit():
            return int(env)
        return shutil.get_terminal_size((80, 24)).columns

    def _color(self) -> bool:
        return self.file.isatty() and os.environ.get("NO_COLOR") is None

    def print(self, *objs: Renderable) -> None:
        color = self._color()
        if not objs:
            self.file.write("\n")
            return
        for obj in objs:
            self.file.write(_render(obj, color) + "\n")

    def rule(self, title: str = "") -> None:
        color = self._color()
        w = self.width
        text = _parse_markup(title)
        label = text.plain
        if label:
            side = max(3, (w - len(label) - 2) // 2)
            line = Text("─" * side + " ", ACCENT_SOFT)
            line.spans += text.spans
            line.append(" " + "─" * max(3, w - side - len(label) - 2), ACCENT_SOFT)
            self.file.write(line.render(color=color) + "\n")
        else:
            self.file.write(Text("─" * w, ACCENT_SOFT).render(color=color) + "\n")


class Live:
    """A minimal full-screen live view: alternate screen buffer, redraw on update."""

    def __init__(self, renderable: Renderable, *, console: Console,
                 refresh_per_second: float = 4, screen: bool = True) -> None:
        self.console = console
        self.screen = screen
        self._renderable = renderable

    def __enter__(self) -> Live:
        if self.screen and self.console.file.isatty():
            self.console.file.write("\x1b[?1049h")
        self._draw()
        return self

    def __exit__(self, *exc) -> None:
        if self.screen and self.console.file.isatty():
            self.console.file.write("\x1b[?1049l")
            self.console.file.flush()

    def _draw(self) -> None:
        if self.console.file.isatty():
            self.console.file.write("\x1b[H\x1b[2J")
        self.console.print(self._renderable)
        self.console.file.flush()

    def update(self, renderable: Renderable) -> None:
        self._renderable = renderable
        self._draw()


console = Console()
err_console = Console(stderr=True)
