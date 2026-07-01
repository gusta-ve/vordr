# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [1.2.0]

### Added
- **`vordr secret rm <provider>`** — remove a stored API token from the secrets file, so you
  can retire or rotate a provider without hand-editing `secrets.toml`. Rounds out
  `secret set`/`status`. An environment variable still takes precedence and is left untouched
  (the command says so).

## [1.1.0]

### Changed
- **Notifications went terminal-log dark.** The push dropped the emoji dots for bracket
  severity tags — `[!!]` critical, `[!]` attention, `[+]` recovered — one clean line per
  alert (`[tag] host · detail`) under a plain `vordr · …` summary. Reads like a log, fits
  the tool's aesthetic.
- **Refreshed the README hero.** It now shows two faux-terminals: the `vordr status` board
  and a `vordr check` notification rendered in the real bracket-tag layout.

## [1.0.0]

The first stable release. Vordr now answers the three day-to-day questions about your
hosts — *are they up?*, *will I be charged?*, *are they secure?* — over plain SSH, with
no agents, no database and no secrets in the repo. The CLI surface (`status`, `resources`,
`security`, `cost`, `billing`, `check`, `setup`, `test`, `init`, `hosts`, `secret`) and its
config are considered stable from here on.

### Added
- **`vordr test`** — send a sample alert through every configured channel on demand. It uses
  the real notification layout (summary line + a colored dot per item), so what lands on your
  device is exactly what a live `vordr check --notify` would send.

### Changed
- **Notifications got a visual refresh.** A push now leads with a one-line summary
  (`🐺 vordr · 1 critical · 1 alert · 1 recovered`) and tags each line with a colored dot
  — 🔴 critical, 🟡 attention, 🟢 recovered — mirroring the terminal's thresholds, so a
  glance at the lock screen is enough.
- **`vordr setup` stops fighting you over configured channels.** Pressing enter now just
  *keeps* what's there. Naming a channel that's already set up offers to **test that one**
  instead of forcing the token again; you only re-enter a token to add or reconfigure a
  channel. An empty token prompt aborts cleanly instead of looping.

### Housekeeping
- Generalized the wording that still implied ntfy was the only channel; the docs and help
  now name all three (Telegram, email, ntfy). Test fixtures use neutral example hosts.

## [0.12.0]

### Added
- **Email notifications (Gmail/SMTP).** A third channel — for the inbox you already watch.
  `vordr secret set email` stores a Gmail app password (chmod 600, outside the repo) and
  `[notify] email` holds the address; `vordr setup` validates the SMTP login before saving.
- **Several channels at once.** `vordr setup` now *adds* a channel instead of replacing the
  others, so you can receive on Telegram **and** email **and** ntfy together — every
  configured channel fires on each alert.

## [0.11.1]

### Changed
- **`vordr setup` schedules by default.** The daily-check prompt now defaults to *yes* (the
  timer is per-user and reversible), so accepting it is enough to be covered. If setup ends
  with nothing scheduled — you decline, or there's no systemd — it prints a clear warning
  that no alert will fire until `vordr check` runs, with the commands to fix it. Closes the
  trap where finishing setup left you feeling protected while nothing actually ran.

## [0.11.0]

### Added
- **Telegram notifications.** Deliver alerts through an app you already use instead of a
  dedicated push app. Store the bot token with `vordr secret set telegram` and the chat id
  in `[notify] telegram_chat`; `vordr setup` now asks which channel you want and, for
  Telegram, auto-detects the chat id from a message you send the bot. ntfy still works, and
  both can run at once.

## [0.10.0]

### Changed
- **`vordr check --notify` only pushes on change.** Standing alerts no longer re-push on
  every run — a notification fires when an alert is *new* or climbs to a more urgent tier
  (upcoming → imminent → due). The ledger lives in `~/.cache/vordr/notify-state.json`. The
  terminal still prints the full picture every time; only the push is deduplicated.

### Added
- **Recovery push for offline hosts.** When a host that was offline answers again, you get
  a one-shot `✓ <host> back online` — the relief after the alarm. Cleared charge/domain/
  runway alerts drop out quietly.
- **Transient-failure tolerance.** A host that fails the first SSH probe is re-probed
  before being declared offline, so a momentary hiccup never fires a false critical push.

## [0.9.1]

### Fixed
- A provider error (e.g. a rejected token) was printed twice in `cost`, `billing` and
  `check`, because both the server and account fetchers reported it. Notes are now
  deduplicated, keeping first-seen order.

## [0.9.0]

### Added
- **`vordr setup`** — a guided, tutorial-style configurator for alerts & notifications.
  Type a value (or accept the default) and it writes only the `[alerts]`/`[notify]`
  sections, generates an ntfy topic, can send a test push, and optionally installs a
  reversible per-user systemd timer. No hand-editing TOML, no copying files.

## [0.8.1]

### Added
- **`vordr check --watch 6h`** — a self-contained interval loop, so scheduling needs no
  system changes. Example per-user systemd units live in `examples/systemd/` (you install
  them; vordr never touches your scheduler).

## [0.8.0]

### Added
- **`vordr check`** — the triage command. Prints only what needs attention and exits
  non-zero if anything does (made for cron): a prepaid bonus/credit about to run out
  (and the card charges that follow), upcoming charges/renewals, expiring domains and
  offline hosts. Thresholds in `[alerts]` (`runway_days` 14, `charge_days` 7).
- **`vordr check --notify`** — push the alerts via **ntfy** (`src/vordr/notify.py`);
  configure with `[notify] ntfy = "..."` or `VORDR_NTFY_URL`.

## [0.7.0]

### Changed
- **Redesigned output — minimal "steel" look.** A silver-gunmetal accent, frameless
  tables (accent header + a single rule), frameless per-host cards and `·`-joined footer
  lines. The new palette/helpers live in `src/vordr/ui.py`.

### Added
- **`docs/hero.svg`** (generated by `docs/make_hero.py`) — the wordmark beside a rendered
  status board; embedded at the top of the README.
- **`examples/config.example.toml`** — a full, commented reference config.

## [0.6.0]

### Changed
- **The whole tool is now in English** — CLI help, messages, output and docs — to match
  the sibling projects (wraith, hickok, deadwood).
- **Repository moved to a `src/` layout** (`src/vordr/`), with the pyproject, ruff and
  pytest config updated to match.

### Added
- **Branded splash on the bare command.** Running `vordr` with no arguments now prints a
  short banner (tagline + quickstart + `vordr -h` hint) instead of the raw Typer help.
- `-h` is now accepted as an alias for `--help`.
- Project meta files: `Makefile`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.

## [0.5.1]

### Changed
- Slimmed down the static config template and `config.example.toml` to the bare minimum,
  making clear the file is optional (the API discovers servers).

## [0.5.0]

### Added
- **Billing-only hosts.** A host with no SSH alias (`ssh = ""`) shows in `cost`/`billing`
  but is skipped (with a notice) by `status`/`resources`/`security`. The `init` wizard
  leaves the alias blank when it can't match one, instead of guessing the server name.

## [0.4.0]

### Added
- **Interactive `vordr init`.** In a terminal it becomes a wizard: it discovers servers
  from the API, suggests the SSH alias from `~/.ssh/config`, and asks for a pinned price.

## [0.3.0]

### Added
- **Automatic server discovery.** `cost` and `billing` list the account's servers from
  any provider with a saved token — the config is now optional.

## [0.2.0]

### Added
- **`vordr billing`** — balance, credit and next charge per provider. Prepaid providers
  (Vultr) show credit, pending usage and runway; postpaid ones (Hetzner) show the next
  charge date and estimated cost.

## [0.1.0]

### Added
- Initial release: `status`, `resources`, `security`, `cost`, `hosts`, `init` over SSH;
  automatic domain expiry via RDAP; provider cost/since via the Hetzner and Vultr APIs;
  tokens stored outside the repo (`vordr secret set`).
