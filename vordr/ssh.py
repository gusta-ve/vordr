"""Camada de transporte: executa comandos nos hosts via SSH.

Vordr nunca guarda IPs nem credenciais. Ele apoia-se inteiramente no seu
`~/.ssh/config` — os hosts são referenciados por *alias* (ex.: ``web``,
``db``). Toda a autenticação é delegada ao SSH (chave, agent, etc.).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 20

# Forçamos um locale neutro para que a saída dos comandos remotos seja estável
# e não venha poluída por avisos de "cannot change locale".
_REMOTE_PREFIX = "LC_ALL=C LANG=C "


@dataclass
class SSHResult:
    """Resultado de um comando remoto."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SSHError(RuntimeError):
    """Falha ao contatar o host (timeout, host inacessível, ssh ausente)."""


def ssh_available() -> bool:
    """Indica se o binário ``ssh`` está disponível no PATH."""
    return shutil.which("ssh") is not None


def config_path() -> Path:
    return Path(os.environ.get("SSH_CONFIG", "~/.ssh/config")).expanduser()


def list_aliases(path: Path | None = None) -> list[str]:
    """Lê os aliases ``Host`` do ``~/.ssh/config`` (ignora padrões com curinga).

    Usado pelo ``vordr init`` para sugerir o alias de cada servidor descoberto.
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
    """Executa ``command`` no host ``alias`` e devolve o resultado.

    ``batch=True`` usa ``BatchMode=yes`` para nunca abrir prompt interativo
    (senha/passphrase) — se a chave não estiver disponível, falha rápido em vez
    de travar o terminal.
    """
    if not ssh_available():
        raise SSHError("binário 'ssh' não encontrado no PATH")

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
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - depende de rede
        raise SSHError(f"timeout ({timeout}s) ao contatar '{alias}'") from exc

    return SSHResult(proc.returncode, proc.stdout, proc.stderr)


def run_passthrough(alias: str, command: str, *, timeout: int = DEFAULT_TIMEOUT) -> int:
    """Executa ``command`` herdando o terminal (mantém cores/ANSI nativos).

    Usado pelo modo ``--raw``, que apenas reproduz a saída original do
    ``status_command`` configurado do host, tal como ela é no servidor.
    """
    if not ssh_available():
        raise SSHError("binário 'ssh' não encontrado no PATH")

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
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - depende de rede
        raise SSHError(f"timeout ({timeout}s) ao contatar '{alias}'") from exc
