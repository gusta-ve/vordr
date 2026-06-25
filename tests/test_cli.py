from typer.testing import CliRunner

from vordr import cli
from vordr.probe import SystemMetrics

runner = CliRunner()


_SAMPLE_CONFIG = """\
[hosts.web]
ssh = "web"
label = "Web"

  [hosts.web.server]
  provider = "Hetzner"
  since = "2024-03-01"
  expires = "2026-08-15"
  cost = 6.99
  currency = "USD"
  cycle = "monthly"

  [hosts.web.domain]
  name = "web.example.com"
  registrar = "Cloudflare"
  expires = "2027-03-01"
  cost = 12.00
  currency = "USD"
  cycle = "yearly"

[hosts.db]
ssh = "db"
label = "DB"

  [hosts.db.server]
  provider = "DigitalOcean"
  expires = "2026-07-30"
  cost = 12.00
  currency = "USD"
  cycle = "monthly"
"""


def _isolate_secrets(monkeypatch, tmp_path):
    """Ensure tests don't read real tokens from the environment or home."""
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)


def _write_config(monkeypatch, tmp_path):
    """Write a generic config and point Vordr at it (without touching the user's)."""
    path = tmp_path / "config.toml"
    path.write_text(_SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    # keep rich from truncating columns at the default width (80) outside a terminal
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    return path


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "vordr" in result.stdout


def test_hosts_lists_configured(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["hosts"])
    assert result.exit_code == 0
    assert "web" in result.stdout.lower()
    assert "db" in result.stdout.lower()


def test_no_config_shows_init_hint(monkeypatch, tmp_path):
    monkeypatch.setenv("VORDR_CONFIG", str(tmp_path / "absent.toml"))
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "no hosts" in result.stdout.lower()


def test_cost_table_lists_providers_and_total(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "cost" in out
    assert "hetzner" in out
    assert "monthly total" in out


def test_cost_panel_for_single_host(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost", "web"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "hosting for" in out
    assert "domain" in out
    assert "cloudflare" in out


def test_cost_fetches_domain_via_rdap_when_only_name(monkeypatch, tmp_path):
    from datetime import date

    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.web]\nssh = "web"\n[hosts.web.domain]\nname = "web.example.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    called = {"name": None}

    def fake_expiry(name, timeout=10):
        called["name"] = name
        return date(2030, 1, 1)

    monkeypatch.setattr(cli.rdap, "domain_expiry", fake_expiry)
    result = runner.invoke(cli.app, ["cost", "web"])
    assert result.exit_code == 0
    assert called["name"] == "web.example.com"
    assert "2030-01-01" in result.stdout
    assert "rdap" in result.stdout.lower()


def test_cost_offline_skips_rdap(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.web]\nssh = "web"\n[hosts.web.domain]\nname = "web.example.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")

    def boom(name, timeout=10):
        raise AssertionError("should not query RDAP in offline mode")

    monkeypatch.setattr(cli.rdap, "domain_expiry", boom)
    result = runner.invoke(cli.app, ["cost", "--offline"])
    assert result.exit_code == 0


def _provider_config(monkeypatch, tmp_path, *, manual_cost=False):
    cost_line = "  cost = 4.99\n  currency = \"EUR\"\n" if manual_cost else ""
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = "box"\nlabel = "Box"\n'
        '  [hosts.box.server]\n  provider = "Hetzner"\n'
        '  provider_server = "ubuntu-box"\n' + cost_line,
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)


def _fake_hetzner(created, net, gross):
    from vordr.hetzner import ServerBilling

    def fetch(token, timeout=15):
        return {"ubuntu-box": ServerBilling("ubuntu-box", created, net, gross, "EUR")}

    return fetch


def test_cost_autofills_from_provider_api(monkeypatch, tmp_path):
    from datetime import date

    _provider_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(cli.hetzner, "fetch_servers", _fake_hetzner(date(2025, 1, 1), 6.49, 6.49))

    result = runner.invoke(cli.app, ["cost", "box"])
    assert result.exit_code == 0
    out = result.stdout
    assert "2025-01-01" in out      # since came from the API
    assert "6.49" in out            # cost came from the API
    assert "(API)" in out           # marked as automatic


def test_manual_cost_overrides_provider_api(monkeypatch, tmp_path):
    from datetime import date

    _provider_config(monkeypatch, tmp_path, manual_cost=True)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(cli.hetzner, "fetch_servers", _fake_hetzner(date(2025, 1, 1), 6.49, 6.49))

    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    # the manual value (4.99) wins over the API's (6.49)
    assert "4.99" in result.stdout
    assert "EUR 4.99" in result.stdout


def test_cost_autofills_from_vultr(monkeypatch, tmp_path):
    from datetime import date

    from vordr.providers import ServerBilling

    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.simplimei]\nssh = "simplimei"\nlabel = "SimpliMei"\n'
        '  [hosts.simplimei.server]\n  provider = "Vultr"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "vultr" else None)
    # label "SimpliMEI-Core-Production" matches the "simplimei" alias by substring
    monkeypatch.setattr(
        cli.vultr,
        "fetch_servers",
        lambda token, timeout=15: {
            "SimpliMEI-Core-Production": ServerBilling(
                "SimpliMEI-Core-Production", date(2026, 5, 20), 48.0, 48.0, "USD"
            )
        },
    )
    result = runner.invoke(cli.app, ["cost", "simplimei"])
    assert result.exit_code == 0
    assert "2026-05-20" in result.stdout
    assert "48.00" in result.stdout
    assert "(API)" in result.stdout


def test_cost_hints_when_provider_token_missing(monkeypatch, tmp_path):
    _provider_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)

    def boom(token, timeout=15):
        raise AssertionError("should not call the API without a token")

    monkeypatch.setattr(cli.hetzner, "fetch_servers", boom)
    result = runner.invoke(cli.app, ["cost", "box"])
    assert result.exit_code == 0
    assert "secret set hetzner" in result.stdout


def test_init_wizard_no_alias_makes_billing_only(monkeypatch, tmp_path):
    """No matching alias and empty enter → 'billing-only' host (empty ssh)."""
    from datetime import date

    from vordr.providers import ServerBilling

    path = tmp_path / "config.toml"
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(
        cli.hetzner,
        "fetch_servers",
        lambda token, timeout=15: {
            "ubuntu-nexus": ServerBilling("ubuntu-nexus", date(2026, 5, 1), 6.49, 6.49, "EUR")
        },
    )
    monkeypatch.setattr(cli.ssh, "list_aliases", lambda: [])  # nenhum alias no ssh config
    # import(enter) / empty alias(enter) / empty price(enter)
    result = runner.invoke(cli.app, ["init"], input="\n\n\n")
    assert result.exit_code == 0
    text = path.read_text()
    assert 'ssh = ""' in text                    # billing-only
    assert 'provider = "Hetzner"' in text
    # the table key comes from the server name
    assert "[hosts.ubuntu-nexus]" in text


def test_status_skips_billing_only_host(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = ""\nlabel = "Box"\n'
        '  [hosts.box.server]\n  provider = "Vultr"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "no ssh alias" in result.stdout.lower()


def test_cost_discovers_servers_without_config(monkeypatch, tmp_path):
    """With a token and no hosts in config, `cost` lists the servers from the API."""
    from datetime import date

    from vordr.providers import ServerBilling

    path = tmp_path / "config.toml"
    path.write_text("[thresholds]\nwarn_days = 14\n", encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(
        cli.hetzner,
        "fetch_servers",
        lambda token, timeout=15: {
            "ubuntu-nexus": ServerBilling("ubuntu-nexus", date(2026, 5, 1), 6.49, 6.49, "EUR")
        },
    )
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    assert "ubuntu-nexus" in result.stdout      # discovered via the API
    assert "6.49" in result.stdout


def test_cost_no_config_no_token_hints(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[thresholds]\nwarn_days = 14\n", encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    assert "secret set" in result.stdout


def test_billing_prepaid_shows_credit_and_runway(monkeypatch, tmp_path):
    from datetime import date

    from vordr.providers import AccountBilling, ServerBilling

    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = "box"\nlabel = "Box"\n'
        '  [hosts.box.server]\n  provider = "Vultr"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "vultr" else None)
    monkeypatch.setattr(
        cli.vultr,
        "fetch_servers",
        lambda token, timeout=15: {
            "Box": ServerBilling("Box", date(2026, 5, 1), 60.0, 60.0, "USD")
        },
    )
    monkeypatch.setattr(
        cli.vultr,
        "fetch_account",
        lambda token, timeout=15: AccountBilling(balance=-193.88, pending_charges=79.02),
    )
    result = runner.invoke(cli.app, ["billing"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Vultr" in out
    assert "193.88" in out          # credit
    assert "114.86" in out          # net
    assert "runway" in out.lower()


def test_billing_postpaid_shows_next_charge(monkeypatch, tmp_path):
    _provider_config(monkeypatch, tmp_path)  # provider = Hetzner
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    result = runner.invoke(cli.app, ["billing", "--offline"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "hetzner" in out
    assert "postpaid" in out


def test_cost_shows_balance_summary_line(monkeypatch, tmp_path):
    from datetime import date

    from vordr.providers import AccountBilling, ServerBilling

    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = "box"\nlabel = "Box"\n'
        '  [hosts.box.server]\n  provider = "Vultr"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "vultr" else None)
    monkeypatch.setattr(
        cli.vultr,
        "fetch_servers",
        lambda token, timeout=15: {
            "Box": ServerBilling("Box", date(2026, 5, 1), 60.0, 60.0, "USD")
        },
    )
    monkeypatch.setattr(
        cli.vultr,
        "fetch_account",
        lambda token, timeout=15: AccountBilling(balance=-193.88, pending_charges=79.02),
    )
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    assert "credit" in result.stdout
    assert "193.88" in result.stdout


def test_secret_status(monkeypatch, tmp_path):
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("HCLOUD_TOKEN", "abcd1234efgh5678")
    result = runner.invoke(cli.app, ["secret", "status"])
    assert result.exit_code == 0
    assert "hetzner" in result.stdout
    assert "abcd…5678" in result.stdout     # masked
    assert "abcd1234efgh5678" not in result.stdout


def test_secret_set_validates_and_writes(monkeypatch, tmp_path):
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.hetzner, "fetch_servers", lambda token, timeout=15: {})
    result = runner.invoke(cli.app, ["secret", "set", "hetzner"], input="my-secret-token\n")
    assert result.exit_code == 0
    saved = (tmp_path / "secrets.toml").read_text()
    assert "my-secret-token" in saved
    # file written with 600 permission
    import stat

    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_secret_set_unknown_provider(monkeypatch, tmp_path):
    _isolate_secrets(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["secret", "set", "aws"], input="x\n")
    assert result.exit_code == 2


def test_init_creates_config(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    _isolate_secrets(monkeypatch, tmp_path)
    # non-interactive (CliRunner) → writes the commented template
    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0
    assert path.exists()
    assert "hosts.web" in path.read_text()
    # second run without --force must fail
    again = runner.invoke(cli.app, ["init"])
    assert again.exit_code == 1


def test_init_wizard_imports_from_api(monkeypatch, tmp_path):
    from datetime import date

    from vordr.providers import ServerBilling

    path = tmp_path / "config.toml"
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(
        cli.hetzner,
        "fetch_servers",
        lambda token, timeout=15: {
            "ubuntu-nexus": ServerBilling("ubuntu-nexus", date(2026, 5, 1), 6.49, 6.49, "EUR")
        },
    )
    monkeypatch.setattr(cli.ssh, "list_aliases", lambda: ["nexus", "db"])
    # confirm import (enter=yes) / default alias (enter) / empty fixed price (enter)
    result = runner.invoke(cli.app, ["init"], input="\n\n\n")
    assert result.exit_code == 0
    text = path.read_text()
    assert 'provider = "Hetzner"' in text
    assert 'ssh = "nexus"' in text          # alias suggested from ubuntu-nexus
    assert "[hosts.nexus]" in text


def test_init_wizard_pins_promo_price(monkeypatch, tmp_path):
    from datetime import date

    from vordr.providers import ServerBilling

    path = tmp_path / "config.toml"
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(
        cli.hetzner,
        "fetch_servers",
        lambda token, timeout=15: {
            "ubuntu-nexus": ServerBilling("ubuntu-nexus", date(2026, 5, 1), 6.49, 6.49, "EUR")
        },
    )
    monkeypatch.setattr(cli.ssh, "list_aliases", lambda: [])
    # import / alias "nexus" / fixed price "4.99"
    result = runner.invoke(cli.app, ["init"], input="\nnexus\n4.99\n")
    assert result.exit_code == 0
    text = path.read_text()
    assert "cost = 4.99" in text


def test_status_uses_probe(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)

    def fake_probe(alias, timeout=20):
        return SystemMetrics(
            reachable=True,
            hostname=alias,
            os="Ubuntu",
            uptime_seconds=3600,
            loadavg=(0.1, 0.1, 0.1),
            cpus=2,
            mem_total_kb=1000,
            mem_avail_kb=600,
            disk_total_kb=1000,
            disk_used_kb=200,
            disk_pct=20,
            docker_running=3,
            docker_total=3,
        )

    monkeypatch.setattr(cli, "probe_system", fake_probe)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "status" in result.stdout.lower()


def test_status_unknown_host(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["status", "naoexiste"])
    assert result.exit_code == 2
