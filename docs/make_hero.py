#!/usr/bin/env python3
"""Generate docs/hero.svg — the vordr wordmark beside two rendered faux-terminals.

Steel theme (silver-gunmetal accent on a dark card), matching the terminal output.
A `vordr status` board on top and a `vordr check` notification below (the real
bracket-tag layout). Run after changing the look:

    python3 docs/make_hero.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "hero.svg"

NAME = "vordr"
TAGLINE = "the warden of your servers"
HOOK = "no agents · no database · just your ~/.ssh/config"
SIG = "gusta-ve · github.com/gusta-ve/vordr"

# palette (steel + severity)
BG, EDGE, PANEL = "#0b0d10", "#1c2128", "#0d1117"
ACCENT, TEXT, MUTED, DIM = "#9cb4d6", "#c9d1d9", "#8b949e", "#6e7681"
OK, WARN, CRIT = "#5fbf73", "#d6a050", "#e5675f"

W, H = 1120, 480
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

PAD, CW, LH, FS = 22, 9.7, 28, 16          # padding, char width, line height, font size

# right column: two stacked faux-terminals
RX, RW = 560, 524
X_END = RX + RW - PAD
TX0 = RX + PAD
A_Y, A_H = 52, 196                         # status board
B_Y, B_H = 264, 196                        # notification card

COL = {"host": 0, "state": 9, "uptime": 22, "ram": 33, "disk": 40}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, fill, *, bold=False, size=FS):
    weight = ' font-weight="700"' if bold else ""
    return (f'<text x="{round(x, 1)}" y="{round(y, 1)}" font-size="{size}" fill="{fill}"'
            f'{weight} xml:space="preserve">{esc(s)}</text>')


def col(n):
    return TX0 + n * CW


def window(svg, y, h, sub):
    """Draw a faux-terminal card (three dots, `vordr · <sub>` title, rule). Returns body-y."""
    svg += [
        f'<rect x="{RX}" y="{y}" width="{RW}" height="{h}" rx="10" '
        f'fill="{PANEL}" stroke="{EDGE}"/>',
        f'<circle cx="{RX + 20}" cy="{y + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{RX + 38}" cy="{y + 20}" r="5" fill="#3a4150"/>',
        f'<circle cx="{RX + 56}" cy="{y + 20}" r="5" fill="#3a4150"/>',
    ]
    title_y = y + 50
    svg.append(text(TX0, title_y, "vordr", ACCENT, bold=True))
    svg.append(text(TX0 + 5 * CW, title_y, f"  ·  {sub}", MUTED))
    svg.append(f'<line x1="{TX0}" y1="{title_y + 12}" x2="{X_END}" y2="{title_y + 12}" '
               f'stroke="{EDGE}"/>')
    return title_y


def main() -> None:
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">',
        '<defs><linearGradient id="wm" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#dbe6f3"/><stop offset="1" stop-color="#3a4d68"/>'
        '</linearGradient></defs>',
        f'<rect width="{W}" height="{H}" rx="14" fill="{BG}" stroke="{EDGE}"/>',
        # left column: wordmark, tagline, hook, install prompt, signature
        f'<text x="56" y="190" font-size="100" font-weight="800" fill="url(#wm)" '
        f'letter-spacing="1">{esc(NAME)}</text>',
        text(62, 230, TAGLINE, MUTED, size=20),
        text(62, 302, HOOK, DIM, size=15),
        text(62, 362, "$", DIM, size=18),
        text(84, 362, "pipx install vordr", ACCENT, size=18),
        text(62, H - 26, SIG, DIM, size=13),
    ]

    # panel A: status board
    y = window(svg, A_Y, A_H, "server status")
    y += LH + 6
    for key in ("host", "state", "uptime", "ram", "disk"):
        svg.append(text(col(COL[key]), y, key, MUTED))
    for name, up, ram, disk in (("web", "2w 5d", "32%", "22%"),
                                ("db", "4w 4d", "18%", "62%")):
        y += LH
        svg.append(text(col(COL["host"]), y, name, TEXT))
        sx = col(COL["state"])
        svg.append(f'<circle cx="{round(sx + 4, 1)}" cy="{y - 5}" r="4" fill="{OK}"/>')
        svg.append(text(sx + 16, y, "online", OK))
        svg.append(text(col(COL["uptime"]), y, up, TEXT))
        svg.append(text(col(COL["ram"]), y, ram, TEXT))
        svg.append(text(col(COL["disk"]), y, disk, TEXT))
    y += LH + 4
    svg.append(text(TX0, y, "total  EUR 4.99 + USD 60.00 / month", DIM))

    # panel B: notification (the real push layout)
    y = window(svg, B_Y, B_H, "check")
    for tag, body, color in (
        ("[!!]", "db · domain expired (2026-06-28)", CRIT),
        ("[!]", "Hetzner · charge in 6d (~ EUR 4.99)", WARN),
        ("[+]", "web · back online", OK),
    ):
        y += LH + 6
        svg.append(text(TX0, y, tag, color, bold=True))
        svg.append(text(col(5), y, body, TEXT))

    svg.append("</svg>")
    OUT.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
