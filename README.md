<p align="center">
  <img src="https://raw.githubusercontent.com/gusta-ve/vordr/main/docs/hero.svg" alt="vordr — the warden of your servers" width="900">
</p>

<p align="center">
  <a href="https://pypi.org/project/vordr/"><img src="https://img.shields.io/pypi/v/vordr?color=9cb4d6&label=pypi" alt="PyPI"></a>
  <a href="https://github.com/gusta-ve/vordr/actions/workflows/ci.yml"><img src="https://github.com/gusta-ve/vordr/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-9cb4d6" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-9cb4d6" alt="MIT"></a>
</p>

> _In Norse lore, the **Vörðr** is the guardian spirit that follows each person from
> birth to death, watching without rest. Here, Vordr stands guard over your servers._

**Vordr** is a CLI that watches your Linux hosts over SSH and answers, in one place,
the questions that matter day to day:

- **Are they up?** — state, uptime, load, RAM, disk and containers for every host.
- **Will I be charged?** — how long you've hosted each one, when the **server** renews
  and when the **domain** expires, and how much you spend per month.
  _The feature that prevents the surprise charge._
- **Are they secure?** — failed logins, listening ports, fail2ban, pending updates and
  reboot-required.

No agents installed on the servers, no database, no secrets in the code: Vordr only
needs your `~/.ssh/config`.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Vordr · server status                                                  │
├───────────┬──────────┬─────────┬──────┬─────┬───────┬────────┬─────────┤
│ host      │ state    │ uptime  │ load │ ram │ disk  │ docker │ expires │
├───────────┼──────────┼─────────┼──────┼─────┼───────┼────────┼─────────┤
│ web       │ ● online │ 2w 5d   │ 0.28 │ 32% │ 22%   │ 5/6    │ 53d     │
│ db        │ ● online │ 4w 4d   │ 0.04 │ 18% │ 62%   │ 6/6    │ 6d  ⚠   │
└───────────┴──────────┴─────────┴──────┴─────┴───────┴────────┴─────────┘
```

## Why it exists

Anyone running a few servers ends up collecting loose commands and repeated logins to
answer simple questions. Vordr folds that into a single layer that:

1. looks at **all hosts at once**, with comparable metrics colored by threshold
   (load per CPU, disk/RAM %);
2. warns **before** a renewal charges again;
3. gives a **quick security audit** without logging into each machine.

Vordr collects metrics via small `sh` scripts that emit `KEY=value` (stable and
testable) instead of parsing fragile colored output — but it still offers a `--raw`
mode that reproduces the native output of a `status_command` of yours, when you set one.

## Install

Requires Python 3.11+ and the `ssh` client configured with the hosts you want to watch.

```bash
pipx install vordr          # recommended (isolated tool on PATH)
# or, for development:
pip install -e ".[dev]"
```

## Quick start (just a token)

For cost and billing you **don't need to configure anything**: give a provider token
and Vordr **discovers your account's servers** on its own.

```bash
vordr secret set hetzner   # or: vordr secret set vultr
vordr cost                 # lists the account's servers, with cost and age
vordr billing              # balance/credit and next charge
```

The `config.toml` is **optional** and only covers what the API can't know: a nice label,
the SSH alias (for `status`/`resources`/`security`) or a **pinned price** that differs
from the list price (promo/legacy). What you write in the config always wins over the API.

## Configuration (optional)

Hosts are **aliases from your `~/.ssh/config`** — no IP, user or key is stored by Vordr.
Each host has two lifecycle blocks: `[hosts.X.server]` (the hosting) and
`[hosts.X.domain]` (the domain) — both with **all-optional** fields, filled from the
API/RDAP when you leave them blank.

```bash
vordr init        # wizard: imports servers from the API and maps SSH aliases
```

In a terminal, `vordr init` is a **wizard**: with a saved token, it lists the account's
servers, suggests the SSH alias for each (reading your `~/.ssh/config`) and asks whether
there's a fixed price to pin — generating the config without you writing TOML. In a
pipe/CI, or without a token, it writes a commented template.

If a server has no SSH alias (you leave it blank, or write `ssh = ""`), it becomes
**billing-only**: it shows in `cost`/`billing`, but `status`/`resources`/`security`
ignore it (with a warning), since there's no way to contact it.

```toml
[thresholds]
warn_days = 14
critical_days = 7

[hosts.web]
ssh = "web"                   # alias in ~/.ssh/config
label = "Web"
# status_command = "my-status"   # optional: your script for `vordr status --raw`

  [hosts.web.server]          # the hosting
  provider = "Hetzner"
  since   = "2024-03-01"      # since when you've hosted (hosting age)
  expires = "2026-08-15"      # YYYY-MM-DD — next server renewal
  cost = 6.99
  currency = "USD"
  cycle = "monthly"           # monthly | yearly

  [hosts.web.domain]          # the domain (optional)
  name = "web.example.com"
  registrar = "Cloudflare"
  expires = "2027-03-01"
  cost = 12.00
  currency = "USD"
  cycle = "yearly"
```

Vordr ships no hosts. Without a config **and** without a token, the commands just point
you to the next step (`vordr secret set` or `vordr init`). The SSH-based commands
(`status`, `resources`, `security`) need the aliases in the config; `cost` and `billing`
work with just the token.

## Usage

```bash
vordr status              # board of all hosts
vordr status web          # a single host
vordr status --watch 5    # refresh every 5s (full screen)
vordr status --raw        # host's native status_command output

vordr resources           # CPU/load, memory and disk in detail
vordr security            # audit: logins, failures, ports, fail2ban, updates
vordr cost                # table: hosting, server/domain renewal, cost/mo
vordr cost web            # detailed lifecycle panel for one host
vordr cost --offline      # no network: uses only the config
vordr billing             # balance/credit and next charge per provider
vordr check               # triage: only what needs attention (for cron)
vordr check --notify      # ...and push the alerts to Telegram / email / ntfy
vordr check --watch 6h    # ...keep it on an interval (no system changes)
vordr setup               # guided setup for alerts & notifications
vordr test                # send a sample alert to your channels (verify the look)
vordr hosts               # lists what's configured

vordr secret set hetzner  # stores the API token (chmod 600, outside the repo)
vordr secret status       # shows which providers have a token (masked)
vordr secret rm vultr     # removes a stored token (env var, if set, still wins)
```

All colors follow thresholds: green (ok), yellow (attention), red (critical) — for
disk/RAM, load per CPU and days until the charge.

## `cost` automation (no typing dates)

`cost` fills in what you didn't provide — **and the config value always wins** (handy
for promo/legacy prices):

- **Domain:** give just `name` in `[hosts.X.domain]` and the expiry comes from **RDAP**
  (public, no credential), cached in `~/.cache/vordr/rdap.json`.
- **Server:** with `provider = "Hetzner"` or `"Vultr"` and a token configured, the
  `since` (creation date) and the **monthly cost** come from the **provider's API**.

Supported providers: **Hetzner** (`HCLOUD_TOKEN`) and **Vultr** (`VULTR_API_KEY`).
Tokens never live in the repository: they're read from an environment variable or from
`~/.config/vordr/secrets.toml` (chmod 600, in `.gitignore`), with env taking precedence.
Configure with `vordr secret set <provider>`. Values coming from the network are tagged
with `(API)` / `(RDAP)`.

> ⚠️ The API price is the **list price** of the type/plan — if your account has a
> promo/locked value, set `cost` in the config (it wins). The **Vultr** API uses an IP
> allowlist and the token is *full-access* (there's no read-only): guard it well.

### Balance and next charge (`vordr billing`)

With a token configured, `vordr billing` answers *when* and *from where* the charge
comes — each provider has a model:

- **Prepaid (e.g. Vultr):** shows **credit**, the cycle's **pending usage** and the
  **runway** — how many days the balance still covers (summing the account's server
  costs) and the date it runs out. Useful when running on a bonus/credit: the card is
  only charged once the balance hits zero. A summary of that line also appears in the
  footer of `vordr cost`.
- **Postpaid (e.g. Hetzner):** the Cloud API **doesn't expose a balance**; `billing`
  shows the **next charge date** (1st of the next month) and the estimated monthly cost.

## Don't get charged by surprise (`vordr check`)

`vordr check` is the triage command — it prints **only what needs attention** and exits
non-zero if anything does, so it's made for cron. It flags:

- a prepaid **bonus/credit about to run out** (and the card charges that follow),
- an **upcoming charge or renewal**, and an **expiring domain**,
- a host that's **offline**.

Set it up in one guided command — type a value, press enter, done:

```bash
vordr setup            # pick a channel, set thresholds, (optionally) a daily timer
vordr check            # quiet when all is well; lists alerts + exit 1 otherwise
vordr check --notify   # also push the alerts to your phone
```

`vordr setup` asks **where alerts should go** and writes only the `[alerts]`/`[notify]`
sections of your config (the rest is left untouched), then can send a test push.

```
  vordr · check

  ▲ Vultr  ·  credit runs out in ~12d (2026-08-20) → card charges begin
  ▲ Hetzner  ·  charge in 6d (≈ EUR 4.99, 2026-07-01)

  2 alert(s), 0 critical
```

Thresholds live in `[alerts]` (`runway_days`, default 14; `charge_days`, default 7).
Three notification channels ship — pick what you already use, or **several at once**
(`vordr setup` adds a channel without dropping the others, and every configured channel
fires on each alert):

- **Telegram** — delivery through an app you already have, no extra install. Create a bot
  with [@BotFather](https://t.me/BotFather) (`/newbot`), then `vordr secret set telegram`
  (the token is stored chmod 600, outside the repo). `vordr setup` auto-detects the chat id
  from a message you send the bot and writes `[notify] telegram_chat`.
- **Email (Gmail)** — for the inbox you already watch. Generate an
  [app password](https://myaccount.google.com/apppasswords) (needs 2FA), then
  `vordr secret set email`; the address goes in `[notify] email`. `vordr setup` checks the
  SMTP login before saving.
- **ntfy** — no account, just a topic; set `[notify] ntfy = "https://ntfy.sh/<topic>"`
  (or `VORDR_NTFY_URL`). Needs the ntfy app (or a browser tab) subscribed to the topic.

A push reads at a glance — a one-line summary, then a terminal-log line per item, tagged by
severity (`[!!]` critical, `[!]` attention, `[+]` recovered):

```
vordr · 1 critical · 1 alert · 1 recovered

[!!] db · domain EXPIRED (2026-06-28)
[!]  Hetzner · charge in 6d (≈ EUR 4.99, 2026-07-01)
[+]  web · back online
```

Run `vordr test` anytime to push a sample alert in this exact layout to every configured
channel — handy right after `vordr setup`, or to confirm a channel still delivers.

### Push only when it changes (no alarm fatigue)

On a timer, a standing alert — say a charge seven days out — would otherwise push on every
single run. `--notify` instead pushes **only when something changes**: when an alert is
**new**, or when it climbs to a more urgent tier (`upcoming → imminent → due`). A host that
recovers gets a one-shot `✓ <host> back online`; alerts that simply clear drop out quietly.
The terminal still shows the full picture on every run — only the *push* is deduplicated.
The small ledger lives in `~/.cache/vordr/notify-state.json`. (A transient SSH hiccup is
re-probed before it's ever called offline, so a blip never wakes your phone.)

### Scheduling — your call, nothing installed for you

`vordr check` runs once and exits; vordr never touches your system scheduler. Pick what
suits you:

- **Self-contained loop** — `vordr check --watch 6h --notify` keeps itself on an interval
  in the foreground (run it in `tmux`, or as the user service below). No system changes.
- **Per-user systemd timer** — a ready-made, fully reversible unit lives in
  [`examples/systemd/`](examples/systemd/): copy it to `~/.config/systemd/user/` and
  `systemctl --user enable --now vordr-check.timer`. It's yours to remove anytime.
- **Your own cron/launchd** — if you already run one, just add `vordr check --notify`.

## How it works

| Layer            | File                   | Responsibility                                  |
|------------------|------------------------|-------------------------------------------------|
| SSH transport    | `src/vordr/ssh.py`     | Runs remote commands (`BatchMode`, timeout).    |
| Metric probe     | `src/vordr/probe.py`   | `sh` scripts → `KEY=value` → dataclasses.       |
| Configuration    | `src/vordr/config.py`  | Reads the TOML; days/cost computation.          |
| Domain expiry    | `src/vordr/rdap.py`    | Public RDAP + on-disk cache (no credential).    |
| Provider API     | `src/vordr/hetzner.py`, `src/vordr/vultr.py` | Read-only clients (since, price, balance). |
| Secrets          | `src/vordr/secrets.py` | Tokens outside the repo (env > chmod-600 file). |
| Alerts / push    | `src/vordr/notify.py`  | `vordr check` push channels (Telegram/email/ntfy).|
| Formatting       | `src/vordr/format.py`  | Pure functions (uptime, bytes, color thresholds).|
| CLI              | `src/vordr/cli.py`     | Typer + Rich; orchestrates everything in parallel.|

Hosts are queried **in parallel** (`ThreadPoolExecutor`), so watching 2 or 10 servers
takes essentially the same time.

### Secure by design

- **Read-only:** Vordr only runs read commands (`/proc`, `df`, `ss`, `last`, …).
- **No secrets in the repository:** hosts are SSH aliases; the real `config.toml` stays
  out of version control (see `.gitignore`).
- **No interactive `sudo`:** privileged checks use `sudo -n` (non-interactive) and
  degrade gracefully when there's no permission — they never block the terminal.
- **`BatchMode`:** if the key isn't available, it fails fast instead of prompting for a
  password.

## Development

```bash
make dev      # pip install -e ".[dev]"
make lint     # ruff check .
make test     # pytest -q
```

The tests never touch the network: the SSH layer is injected (`monkeypatch`) and the
parsing/formatting logic is tested against real samples of server output. A full sample
config lives in [`examples/config.example.toml`](examples/config.example.toml); the
README hero is regenerated with `python3 docs/make_hero.py`.

## License

MIT — see [LICENSE](LICENSE).
