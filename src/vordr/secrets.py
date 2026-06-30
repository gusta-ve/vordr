"""Provider API tokens — stored *outside* the repository.

Read precedence: **environment variable > secrets file**. The file
(``~/.config/vordr/secrets.toml`` or ``$VORDR_SECRETS``) is created with ``600``
permissions and is in ``.gitignore``. Configure it with ``vordr secret set <provider>``
— Vordr never reads tokens from the versioned config.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# provider -> equivalent environment variable (the env one takes precedence)
ENV_VARS = {
    "hetzner": "HCLOUD_TOKEN",
    "vultr": "VULTR_API_KEY",
    "telegram": "VORDR_TELEGRAM_TOKEN",   # notify channel, not a cloud provider
    "email": "VORDR_EMAIL_PASSWORD",      # SMTP app password for the email channel
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
    """Provider token: env first, otherwise the secrets file."""
    provider = provider.lower()
    env_name = ENV_VARS.get(provider)
    if env_name:
        val = os.environ.get(env_name)
        if val and val.strip():
            return val.strip()
    val = _load().get("tokens", {}).get(provider)
    return val.strip() if isinstance(val, str) and val.strip() else None


def token_source(provider: str) -> str | None:
    """Where the token would come from: ``"env"``, ``"file"`` or ``None`` — without revealing it."""
    provider = provider.lower()
    env_name = ENV_VARS.get(provider)
    if env_name and os.environ.get(env_name, "").strip():
        return "env"
    val = _load().get("tokens", {}).get(provider)
    if isinstance(val, str) and val.strip():
        return "file"
    return None


def set_token(provider: str, token: str) -> Path:
    """Write the token to the secrets file (chmod 600). Returns the path."""
    provider = provider.lower()
    data = _load()
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}
    tokens[provider] = token.strip()
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Vordr secrets — DO NOT commit. Manage with `vordr secret`.", "", "[tokens]"]
    for key, value in sorted(tokens.items()):
        esc = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{esc}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def mask(token: str) -> str:
    """Show just enough to recognize the token, without exposing it."""
    token = token.strip()
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"
