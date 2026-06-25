# Vordr 🐺

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
vordr hosts               # lists what's configured

vordr secret set hetzner  # stores the API token (chmod 600, outside the repo)
vordr secret status       # shows which providers have a token (masked)
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

## How it works

| Layer            | File                   | Responsibility                                  |
|------------------|------------------------|-------------------------------------------------|
| SSH transport    | `src/vordr/ssh.py`     | Runs remote commands (`BatchMode`, timeout).    |
| Metric probe     | `src/vordr/probe.py`   | `sh` scripts → `KEY=value` → dataclasses.       |
| Configuration    | `src/vordr/config.py`  | Reads the TOML; days/cost computation.          |
| Domain expiry    | `src/vordr/rdap.py`    | Public RDAP + on-disk cache (no credential).    |
| Provider API     | `src/vordr/hetzner.py`, `src/vordr/vultr.py` | Read-only clients (since, price, balance). |
| Secrets          | `src/vordr/secrets.py` | Tokens outside the repo (env > chmod-600 file). |
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
pip install -e ".[dev]"
ruff check .
pytest
```

The tests never touch the network: the SSH layer is injected (`monkeypatch`) and the
parsing/formatting logic is tested against real samples of server output.

## License

MIT — see [LICENSE](LICENSE).
