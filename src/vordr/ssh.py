"""Transport layer: run commands on hosts over SSH.

Vordr never stores IPs or credentials. It relies entirely on your `~/.ssh/config` —
hosts are referenced by *alias* (e.g. ``web``, ``db``). All authentication is
delegated to SSH (key, agent, etc.).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 20

# We force a neutral locale so the remote command output is stable and not polluted
# by "cannot change locale" warnings.
_REMOTE_PREFIX = "LC_ALL=C LANG=C "


@dataclass
class SSHResult:
    """Result of a remote command."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SSHError(RuntimeError):
    """Failure contacting the host (timeout, unreachable host, ssh missing)."""


def ssh_available() -> bool:
    """Whether the ``ssh`` binary is available on PATH."""
    return shutil.which("ssh") is not None


def config_path() -> Path:
    return Path(os.environ.get("SSH_CONFIG", "~/.ssh/config")).expanduser()


def list_aliases(path: Path | None = None) -> list[str]:
    """Read the ``Host`` aliases from ``~/.ssh/config`` (skips wildcard patterns).

    Used by ``vordr init`` to suggest the alias for each discovered server.
    """
    path = path or config_path()
    if not path.exists():
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        if key.lower() != "host":
            continue
        for token in rest.replace("\t", " ").split():
            if any(c in token for c in "*?!") or token in seen:
                continue
            seen.add(token)
            aliases.append(token)
    return aliases


def run(
    alias: str,
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    batch: bool = True,
) -> SSHResult:
    """Run ``command`` on host ``alias`` and return the result.

    ``batch=True`` uses ``BatchMode=yes`` to never open an interactive prompt
    (password/passphrase) — if the key isn't available it fails fast instead of
    blocking the terminal.
    """
    if not ssh_available():
        raise SSHError("'ssh' binary not found on PATH")

    argv = ["ssh"]
    if batch:
        argv += ["-o", "BatchMode=yes"]
    argv += [
        "-o",
        f"ConnectTimeout={max(1, timeout - 2)}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        alias,
        _REMOTE_PREFIX + command,
    ]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - network dependent
        raise SSHError(f"timeout ({timeout}s) contacting '{alias}'") from exc

    return SSHResult(proc.returncode, proc.stdout, proc.stderr)


def run_passthrough(alias: str, command: str, *, timeout: int = DEFAULT_TIMEOUT) -> int:
    """Run ``command`` inheriting the terminal (keeps native colors/ANSI).

    Used by ``--raw`` mode, which just reproduces the original output of the host's
    configured ``status_command``, exactly as it is on the server.
    """
    if not ssh_available():
        raise SSHError("'ssh' binary not found on PATH")

    argv = [
        "ssh",
        "-t",
        "-o",
        f"ConnectTimeout={max(1, timeout - 2)}",
        alias,
        command,
    ]
    try:
        return subprocess.call(argv, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - network dependent
        raise SSHError(f"timeout ({timeout}s) contacting '{alias}'") from exc
