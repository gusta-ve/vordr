# Contributing

Thanks for taking a look. vordr is an SSH-based server monitor: status, resources,
cost/expiry and a quick security audit — all from your `~/.ssh/config`, with no agents
and no database.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The only runtime dependencies are `typer` and `rich`; everything else is the standard
library.

## Ways to contribute

- **Providers** — the cloud clients live in `src/vordr/`. A new one is a small module
  (`fetch_servers`, optionally `fetch_account`, a `BILLING_MODEL`) sharing the types in
  `src/vordr/providers.py`, plus a line in `_PROVIDER_CLIENTS` in `src/vordr/cli.py`.
- **Probes** — `src/vordr/probe.py` holds the portable `sh` scripts that emit
  `KEY=value`; keep them POSIX and tolerant of missing commands.
- **Formatting** — pure helpers (uptime, bytes, color thresholds) live in
  `src/vordr/format.py` and are trivially testable.

## Ground rules

- Keep the runtime light (`typer` + `rich`, standard library otherwise).
- Run `ruff check .` and `pytest` before opening a PR — CI runs them on Python 3.11–3.12.
- Tests never touch the network or real hosts: the SSH and provider layers are injected
  with `monkeypatch`.
