#!/usr/bin/env python3
"""Generate docs/hero.svg — the vordr wordmark beside two rendered faux-terminals.

Steel theme (silver-gunmetal accent on a dark card), matching the terminal output.
The panels double as the demo: a `vordr status` board on top, and a `vordr check`
notification (the real bracket-tag push layout) below. Run after changing the look:

    python3 docs/make_hero.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "hero.svg"

NAME = "vordr"
TAGLINE = "the warden of your servers"
SIG = "gusta-ve · github.com/gusta-ve/vordr · Vörðr, the Norse guardian spirit"

# palette (steel + severity)
BG, EDGE, PANEL = "#0b0d10", "#1c2128", "#0d1117"
ACCENT, TEXT, MUTED, DIM = "#9cb4d6", "#c9d1d9", "#8b949e", "#6e7681"
OK, WARN, CRIT = "#5fbf73", "#d6a050", "#e5675f"

W, H = 1120, 500
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

PAD, CW, LH, FS = 22, 9.7, 28, 16          # padding, char width, line height, font size

# right column: two stacked faux-terminals
RX, RW = 560, 524
A_Y, A_H = 64, 200                         # status board
B_Y, B_H = A_Y + A_H + 22, 178             # notification card

# char columns for the status table
COL = {"host": 0, "state": 9, "uptime": 22, "ram": 33, "disk": 40}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, fill, *, bold=False, size=FS):
    weight = ' font-weight="700"' if bold else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"{weight} '
            f'xml:space="preserve">{esc(s)}</text>')


def panel(x, y, w, h):
    """A faux-terminal card with three window dots; returns (svg parts, text-origin x)."""
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        f'fill="{PANEL}" stroke="{EDGE}"/>',
        f'<circle cx="{x + 20}" cy="{y + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{x + 38}" cy="{y + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{x + 56}" cy="{y + 20}" r="5" fill="#3a4150"/>',
    ]
    return parts, x + PAD


def header(svg, tx0, y, sub, x_end):
    """Panel title `vordr · <sub>` plus the rule under it. Returns the next baseline y."""
    svg.append(text(tx0, y, "vordr", ACCENT, bold=True))
    svg.append(text(tx0 + 5 * CW, y, f"  ·  {sub}", MUTED))
    svg.append(f'<line x1="{tx0}" y1="{y + 12}" x2="{x_end}" y2="{y + 12}" stroke="{EDGE}"/>')
    return y + LH + 6


def main() -> None:
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">',
        '<defs><linearGradient id="wm" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#dbe6f3"/><stop offset="1" stop-color="#3a4d68"/>'
        '</linearGradient></defs>',
        f'<rect width="{W}" height="{H}" rx="14" fill="{BG}" stroke="{EDGE}"/>',
        # wordmark + tagline + hook + install (left column)
        f'<text x="56" y="190" font-size="100" font-weight="800" fill="url(#wm)" '
        f'letter-spacing="1">{esc(NAME)}</text>',
        text(62, 230, TAGLINE, MUTED, size=20),
        text(62, 300, "no agents · no database · just your ~/.ssh/config", DIM, size=15),
        text(62, 360, "$", DIM, size=18),
        text(84, 360, "pipx install vordr", ACCENT, size=18),
        text(62, H - 28, SIG, DIM, size=13),
    ]
    x_end = RX + RW - PAD

    # --- panel A: status board ------------------------------------------------
    parts, tx0 = panel(RX, A_Y, RW, A_H)
    svg += parts
    y = header(svg, tx0, A_Y + 50, "server status", x_end)
    for key, label in (("host", "host"), ("state", "state"), ("uptime", "uptime"),
                       ("ram", "ram"), ("disk", "disk")):
        svg.append(text(round(tx0 + COL[key] * CW, 1), y, label, MUTED))
    for name, up, ram, disk in (("web", "2w 5d", "32%", "22%"),
                                ("db", "4w 4d", "18%", "62%")):
        y += LH
        svg.append(text(round(tx0 + COL["host"] * CW, 1), y, name, TEXT))
        sx = round(tx0 + COL["state"] * CW, 1)
        svg.append(f'<circle cx="{sx + 4}" cy="{y - 5}" r="4" fill="{OK}"/>')
        svg.append(text(sx + 16, y, "online", OK))
        svg.append(text(round(tx0 + COL["uptime"] * CW, 1), y, up, TEXT))
        svg.append(text(round(tx0 + COL["ram"] * CW, 1), y, ram, TEXT))
        svg.append(text(round(tx0 + COL["disk"] * CW, 1), y, disk, TEXT))
    y += LH + 6
    svg.append(text(tx0, y, "total  EUR 4.99 + USD 60.00  ·  credit ~57d left", DIM))

    # --- panel B: notification (the real push layout) -------------------------
    parts, tx0 = panel(RX, B_Y, RW, B_H)
    svg += parts
    y = header(svg, tx0, B_Y + 50, "check  ·  1 critical · 1 alert · 1 recovered", x_end)
    content_x = round(tx0 + 5 * CW, 1)
    for tag, body, color in (
        ("[!!]", "db · domain expired (2026-06-28)", CRIT),
        ("[!]", "Hetzner · charge in 6d (~ EUR 4.99)", WARN),
        ("[+]", "web · back online", OK),
    ):
        y += LH
        svg.append(text(tx0, y, tag, color, bold=True))
        svg.append(text(content_x, y, body, TEXT))

    svg.append("</svg>")
    OUT.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
