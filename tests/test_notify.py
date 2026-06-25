import urllib.request

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
