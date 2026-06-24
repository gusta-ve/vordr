import stat

from vordr import secrets


def test_set_and_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    path = secrets.set_token("hetzner", "  token-123  ")
    assert secrets.get_token("hetzner") == "token-123"  # stripped
    assert secrets.token_source("hetzner") == "file"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_env_takes_precedence_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    secrets.set_token("hetzner", "from-file")
    monkeypatch.setenv("HCLOUD_TOKEN", "from-env")
    assert secrets.get_token("hetzner") == "from-env"
    assert secrets.token_source("hetzner") == "env"


def test_get_token_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "nope.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    assert secrets.get_token("hetzner") is None
    assert secrets.token_source("hetzner") is None


def test_set_token_preserves_other_providers(monkeypatch, tmp_path):
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    secrets.set_token("hetzner", "h-token")
    secrets.set_token("vultr", "v-token")
    assert secrets.get_token("hetzner") == "h-token"
    assert secrets.get_token("vultr") == "v-token"


def test_mask():
    assert secrets.mask("abcd1234efgh") == "abcd…efgh"
    assert secrets.mask("short") == "•••••"
