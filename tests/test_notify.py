import json
import urllib.request

import pytest

from vordr import notify


def test_ntfy_url_resolution(monkeypatch):
    monkeypatch.delenv("VORDR_NTFY_URL", raising=False)
    assert notify.ntfy_url("https://ntfy.sh/x") == "https://ntfy.sh/x"
    assert notify.ntfy_url("mytopic") == "https://ntfy.sh/mytopic"   # bare topic
    assert notify.ntfy_url(None) is None
    assert notify.ntfy_url("  ") is None


def test_ntfy_url_env_wins(monkeypatch):
    monkeypatch.setenv("VORDR_NTFY_URL", "https://n.example/env")
    assert notify.ntfy_url("https://ntfy.sh/x") == "https://n.example/env"


class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""


def test_send_posts_to_ntfy(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        seen["body"] = req.data
        seen["title"] = req.headers.get("Title")
        seen["priority"] = req.headers.get("Priority")
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    sent = notify.send("vordr · 1 alert", "- Vultr: bonus ending",
                       ntfy="https://ntfy.sh/topic", critical=True)
    assert sent == ["ntfy"]
    assert seen["url"] == "https://ntfy.sh/topic"
    assert seen["body"] == b"- Vultr: bonus ending"
    assert seen["title"] == "vordr · 1 alert"
    assert seen["priority"] == "high"


def test_send_no_channel_configured():
    assert notify.send("t", "b", ntfy=None) == []


class _JsonResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_telegram_validate_ok(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=10: _JsonResp({"ok": True, "result": {"username": "vordr_demo_bot"}}),
    )
    assert notify.telegram_validate("123:ABC") == "vordr_demo_bot"


def test_telegram_validate_rejected(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10: _JsonResp({"ok": False}))
    with pytest.raises(notify.NotifyError):
        notify.telegram_validate("bad")


def test_telegram_chat_id_takes_latest(monkeypatch):
    payload = {"ok": True, "result": [
        {"message": {"chat": {"id": 111}}},
        {"message": {"chat": {"id": 222}}},
    ]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=10: _JsonResp(payload))
    assert notify.telegram_chat_id("t") == "222"


def test_send_posts_to_telegram(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        seen["body"] = req.data
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    sent = notify.send("vordr · 1 update", "! web: offline", telegram=("123:ABC", "555"))
    assert sent == ["telegram"]
    assert "api.telegram.org" in seen["url"]
    assert b"chat_id=555" in seen["body"]
    assert b"offline" in seen["body"]


def test_send_telegram_skipped_when_incomplete():
    assert notify.send("t", "b", telegram=(None, "555")) == []   # no token
    assert notify.send("t", "b", telegram=("123", None)) == []   # no chat


def test_send_posts_to_email(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            captured["host"], captured["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, user, password):
            captured["login"] = (user, password)

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    target = notify.EmailTarget("smtp.gmail.com", 587, "me@gmail.com", "app-pw", "you@gmail.com")
    sent = notify.send("vordr · test", "! web: offline", email=target)
    assert sent == ["email"]
    assert captured["tls"] is True
    assert captured["login"] == ("me@gmail.com", "app-pw")
    assert captured["msg"]["To"] == "you@gmail.com"
    assert captured["msg"]["Subject"] == "vordr · test"
    assert "offline" in captured["msg"].get_content()


def test_email_validate_raises_on_login_failure(monkeypatch):
    import smtplib

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, p):
            raise smtplib.SMTPAuthenticationError(535, b"bad app password")

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    target = notify.EmailTarget("smtp.gmail.com", 587, "me@gmail.com", "wrong", "me@gmail.com")
    with pytest.raises(notify.NotifyError):
        notify.email_validate(target)
