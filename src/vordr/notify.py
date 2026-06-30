"""Push notifications for `vordr check --notify`.

Three channels ship today (configure as many as you like — every one fires):

- **Telegram** — for delivery through an app you already use. Configure the bot token as
  a secret (``vordr secret set telegram``) and the chat id in ``[notify] telegram_chat``.
- **Email** — a plain Gmail-style SMTP message. The app password is a secret
  (``vordr secret set email``); the address lives in ``[notify] email``.
- **ntfy** (https://ntfy.sh) — no account, just a topic URL. Configure with
  ``[notify] ntfy = "https://ntfy.sh/<your-topic>"`` (or ``VORDR_NTFY_URL``).

The dispatcher is intentionally small and pluggable: add a channel by writing one
``_send_<name>`` helper and wiring it into :func:`send`.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import NamedTuple

DEFAULT_TIMEOUT = 10
_TG_API = "https://api.telegram.org/bot{token}/{method}"


class EmailTarget(NamedTuple):
    """Everything :func:`_send_email` needs (the password is a secret, kept off config)."""
    host: str
    port: int
    user: str
    password: str
    to: str


class NotifyError(RuntimeError):
    """A configured channel failed to deliver."""


def ntfy_url(config_value: str | None) -> str | None:
    """Resolve the ntfy URL: ``VORDR_NTFY_URL`` env wins over the config value."""
    env = os.environ.get("VORDR_NTFY_URL")
    url = (env or config_value or "").strip()
    if not url:
        return None
    # accept a bare topic ("my-topic") as a convenience
    if "://" not in url:
        url = f"https://ntfy.sh/{url}"
    return url


def _send_ntfy(url: str, title: str, body: str, *, timeout: int, priority: str) -> None:
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,         # "high" for criticals, "default" otherwise
            "Tags": "warning",
            "User-Agent": "vordr",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (user URL)
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise NotifyError(f"ntfy: {exc}") from exc


def _tg_get(token: str, method: str, *, timeout: int) -> dict:
    """Call a Telegram Bot API method (GET) and return the decoded JSON payload."""
    url = _TG_API.format(token=urllib.parse.quote(token, safe=""), method=method)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed host)
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NotifyError(f"telegram: {exc}") from exc


def telegram_validate(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Return the bot's ``@username`` if the token is valid, else raise NotifyError."""
    data = _tg_get(token, "getMe", timeout=timeout)
    if not data.get("ok"):
        raise NotifyError("telegram: token rejected")
    return data.get("result", {}).get("username", "")


def telegram_chat_id(token: str, *, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """The most-recent chat id that has messaged the bot (via getUpdates), or None.

    This is how setup auto-detects where to send: the user messages their bot once,
    and the chat id falls out of the latest update — no manual id hunting.
    """
    data = _tg_get(token, "getUpdates", timeout=timeout)
    if not data.get("ok"):
        return None
    for upd in reversed(data.get("result", [])):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None


def _send_telegram(token: str, chat_id: str, title: str, body: str, *, timeout: int) -> None:
    text = f"{title}\n\n{body}" if body else title
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = _TG_API.format(token=urllib.parse.quote(token, safe=""), method="sendMessage")
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"User-Agent": "vordr"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed host)
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise NotifyError(f"telegram: {exc}") from exc


def _smtp_send(target: EmailTarget, build, *, timeout: int) -> None:
    """Open an authenticated Gmail-style SMTP session (STARTTLS) and run ``build(session)``."""
    try:
        with smtplib.SMTP(target.host, target.port, timeout=timeout) as session:
            session.starttls()
            session.login(target.user, target.password)
            build(session)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"email: {exc}") from exc


def email_validate(target: EmailTarget, *, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Verify the SMTP credentials by logging in (and nothing else), else raise NotifyError."""
    _smtp_send(target, lambda _session: None, timeout=timeout)


def _send_email(target: EmailTarget, title: str, body: str, *, timeout: int) -> None:
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = target.user
    msg["To"] = target.to
    msg.set_content(body or title)
    _smtp_send(target, lambda session: session.send_message(msg), timeout=timeout)


def send(
    title: str,
    body: str,
    *,
    ntfy: str | None = None,
    telegram: tuple[str | None, str | None] | None = None,
    email: EmailTarget | None = None,
    critical: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    """Deliver to every configured channel. Returns the list of channels reached.

    Raises :class:`NotifyError` if a configured channel fails; returns an empty list
    when nothing is configured (the caller decides whether that's an error).
    """
    sent: list[str] = []
    url = ntfy_url(ntfy)
    if url:
        _send_ntfy(url, title, body, timeout=timeout, priority="high" if critical else "default")
        sent.append("ntfy")
    if telegram:
        token, chat = telegram
        if token and chat:
            _send_telegram(token, chat, title, body, timeout=timeout)
            sent.append("telegram")
    if email:
        _send_email(email, title, body, timeout=timeout)
        sent.append("email")
    return sent
