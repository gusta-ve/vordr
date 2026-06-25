#!/usr/bin/env python3
"""Generate docs/hero.svg — the vordr wordmark beside a rendered status board.

Steel theme (silver-gunmetal accent on a dark card), matching the terminal output.
The board doubles as the demo: it shows what `vordr status` looks like. Run after
changing the look:

    python3 docs/make_hero.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "hero.svg"

NAME = "vordr"
TAGLINE = "the warden of your servers"
SIG = "gusta-ve · github.com/gusta-ve/vordr · Vörðr, the Norse guardian spirit"

# palette (steel)
BG, EDGE, PANEL = "#0b0d10", "#1c2128", "#0d1117"
ACCENT, TEXT, MUTED, DIM, OK = "#9cb4d6", "#c9d1d9", "#8b949e", "#6e7681", "#5fbf73"

W, H = 1120, 420
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# board geometry (a faux terminal on the right)
BX, BY, BW, BH = 560, 96, 524, 270
PAD, CW, LH, FS = 22, 9.7, 30, 16          # padding, char width, line height, font size
TX0 = BX + PAD                             # text origin x
TY0 = BY + 62                              # first text row baseline

# char columns for the status table
COL = {"host": 0, "state": 9, "uptime": 22, "ram": 33, "disk": 40}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cx(col: int) -> float:
    return round(TX0 + col * CW, 1)


def text(x, y, s, fill, *, bold=False, size=FS):
    weight = ' font-weight="700"' if bold else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"{weight} '
            f'xml:space="preserve">{esc(s)}</text>')


def main() -> None:
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">',
        '<defs><linearGradient id="wm" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#dbe6f3"/><stop offset="1" stop-color="#3a4d68"/>'
        '</linearGradient></defs>',
        f'<rect width="{W}" height="{H}" rx="14" fill="{BG}" stroke="{EDGE}"/>',
        # wordmark + tagline + signature (left column)
        f'<text x="56" y="190" font-size="104" font-weight="800" fill="url(#wm)" '
        f'letter-spacing="1">{esc(NAME)}</text>',
        text(62, 232, TAGLINE, MUTED, size=20),
        text(62, H - 30, SIG, DIM, size=13),
        # board panel (the demo)
        f'<rect x="{BX}" y="{BY}" width="{BW}" height="{BH}" rx="10" '
        f'fill="{PANEL}" stroke="{EDGE}"/>',
        f'<circle cx="{BX + 20}" cy="{BY + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{BX + 38}" cy="{BY + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{BX + 56}" cy="{BY + 20}" r="5" fill="#3a4150"/>',
    ]

    y = TY0
    # title
    svg.append(text(TX0, y, "vordr", ACCENT, bold=True))
    svg.append(text(TX0 + 5 * CW, y, "  ·  server status", MUTED))
    # divider line
    svg.append(f'<line x1="{TX0}" y1="{y + 12}" x2="{BX + BW - PAD}" y2="{y + 12}" '
               f'stroke="{EDGE}"/>')
    # header
    y += LH + 6
    for key, label in (("host", "host"), ("state", "state"), ("uptime", "uptime"),
                       ("ram", "ram"), ("disk", "disk")):
        svg.append(text(cx(COL[key]), y, label, MUTED))
    # data rows
    for name, up, ram, disk in (("web", "2w 5d", "32%", "22%"),
                                ("db", "4w 4d", "18%", "62%")):
        y += LH
        svg.append(text(cx(COL["host"]), y, name, TEXT))
        svg.append(f'<circle cx="{cx(COL["state"]) + 4}" cy="{y - 5}" r="4" fill="{OK}"/>')
        svg.append(text(cx(COL["state"]) + 16, y, "online", OK))
        svg.append(text(cx(COL["uptime"]), y, up, TEXT))
        svg.append(text(cx(COL["ram"]), y, ram, TEXT))
        svg.append(text(cx(COL["disk"]), y, disk, TEXT))
    # footer
    y += LH + 8
    svg.append(text(TX0, y, "total  EUR 4.99 + USD 60.00", DIM))
    y += LH - 4
    svg.append(text(TX0, y, "Vultr  ·  credit USD 193.88  ·  ~57d left", DIM))

    svg.append("</svg>")
    OUT.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
