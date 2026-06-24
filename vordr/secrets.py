"""Tokens de API de provedores — guardados *fora* do repositório.

Precedência de leitura: **variável de ambiente > arquivo de segredos**. O arquivo
(``~/.config/vordr/secrets.toml`` ou ``$VORDR_SECRETS``) é criado com permissão
``600`` e está no ``.gitignore``. Configure-o com ``vordr secret set <provedor>`` —
o Vordr nunca lê tokens do config versionado.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# provedor -> variável de ambiente equivalente (a do env tem prioridade)
ENV_VARS = {
    "hetzner": "HCLOUD_TOKEN",
    "vultr": "VULTR_API_KEY",
}


def secrets_path() -> Path:
    env = os.environ.get("VORDR_SECRETS")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "vordr" / "secrets.toml"


def _load() -> dict:
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def get_token(provider: str) -> str | None:
    """Token do provedor: env primeiro, senão o arquivo de segredos."""
    provider = provider.lower()
    env_name = ENV_VARS.get(provider)
    if env_name:
        val = os.environ.get(env_name)
        if val and val.strip():
            return val.strip()
    val = _load().get("tokens", {}).get(provider)
    return val.strip() if isinstance(val, str) and val.strip() else None


def token_source(provider: str) -> str | None:
    """De onde viria o token: ``"env"``, ``"file"`` ou ``None`` — sem revelá-lo."""
    provider = provider.lower()
    env_name = ENV_VARS.get(provider)
    if env_name and os.environ.get(env_name, "").strip():
        return "env"
    val = _load().get("tokens", {}).get(provider)
    if isinstance(val, str) and val.strip():
        return "file"
    return None


def set_token(provider: str, token: str) -> Path:
    """Grava o token no arquivo de segredos (chmod 600). Devolve o caminho."""
    provider = provider.lower()
    data = _load()
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}
    tokens[provider] = token.strip()
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Segredos do Vordr — NÃO versionar. Gerencie com `vordr secret`.", "", "[tokens]"]
    for key, value in sorted(tokens.items()):
        esc = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{esc}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def mask(token: str) -> str:
    """Mostra só o suficiente pra reconhecer o token, sem expô-lo."""
    token = token.strip()
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"
