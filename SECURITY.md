# Security policy

## Scope

This policy covers vulnerabilities **in vordr itself** — not the servers you point it at.

## Reporting

Report privately via GitHub Security Advisories ("Report a vulnerability" on the
repository's Security tab), or open a minimal issue if it is not sensitive. Please
include a description, affected version (`vordr --version`) and steps to reproduce.
Expect an initial response within a few days.

## Design notes

- **Read-only:** vordr only runs read commands on the hosts (`/proc`, `df`, `ss`,
  `last`, …) over SSH, and only read (`GET`) calls against provider APIs.
- **No secrets in the repository:** hosts are SSH aliases; the real `config.toml` and
  the provider tokens (`~/.config/vordr/secrets.toml`, chmod 600) stay out of version
  control. Tokens are never read from the versioned config.
- **No interactive `sudo`:** privileged checks use `sudo -n` and degrade gracefully.

## Responsible use

Only point vordr at systems you operate or are authorized to monitor.
