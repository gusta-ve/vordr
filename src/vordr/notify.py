"""Push notifications for `vordr check --notify`.

The first (and simplest) channel is **ntfy** (https://ntfy.sh): no account, just a
topic URL — `vordr` POSTs the alert body to it and it lands on your phone. Configure it
with ``[notify] ntfy = "https://ntfy.sh/<your-topic>"`` (or ``VORDR_NTFY_URL``).

The dispatcher is intentionally small and pluggable: add a channel by writing one
``_send_<name>`` helper and wiring it into :func:`send`.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 10


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


def send(
    title: str,
    body: str,
    *,
    ntfy: str | None,
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
    return sent
