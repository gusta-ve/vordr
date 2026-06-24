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
    """Garante que os testes não leiam tokens reais do ambiente nem do home."""
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)


def _write_config(monkeypatch, tmp_path):
    """Escreve um config genérico e aponta o Vordr para ele (sem tocar no do usuário)."""
    path = tmp_path / "config.toml"
    path.write_text(_SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    # evita o rich truncar colunas na largura padrão (80) fora de um terminal
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
    assert "nenhum host" in result.stdout.lower()


def test_cost_table_lists_providers_and_total(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "custo" in out
    assert "hetzner" in out
    assert "total mensal" in out


def test_cost_panel_for_single_host(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost", "web"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "hospedando há" in out
    assert "domínio" in out
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
        raise AssertionError("não deveria consultar RDAP no modo offline")

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
    assert "2025-01-01" in out      # since veio da API
    assert "6.49" in out            # custo veio da API
    assert "(API)" in out           # marcado como automático


def test_manual_cost_overrides_provider_api(monkeypatch, tmp_path):
    from datetime import date

    _provider_config(monkeypatch, tmp_path, manual_cost=True)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: "tok" if p == "hetzner" else None)
    monkeypatch.setattr(cli.hetzner, "fetch_servers", _fake_hetzner(date(2025, 1, 1), 6.49, 6.49))

    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    # o valor manual (4.99) vence o da API (6.49)
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
    # label "SimpliMEI-Core-Production" casa com o alias "simplimei" por substring
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
        raise AssertionError("não deveria chamar a API sem token")

    monkeypatch.setattr(cli.hetzner, "fetch_servers", boom)
    result = runner.invoke(cli.app, ["cost", "box"])
    assert result.exit_code == 0
    assert "secret set hetzner" in result.stdout


def test_secret_status(monkeypatch, tmp_path):
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("HCLOUD_TOKEN", "abcd1234efgh5678")
    result = runner.invoke(cli.app, ["secret", "status"])
    assert result.exit_code == 0
    assert "hetzner" in result.stdout
    assert "abcd…5678" in result.stdout     # mascarado
    assert "abcd1234efgh5678" not in result.stdout


def test_secret_set_validates_and_writes(monkeypatch, tmp_path):
    _isolate_secrets(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.hetzner, "fetch_servers", lambda token, timeout=15: {})
    result = runner.invoke(cli.app, ["secret", "set", "hetzner"], input="my-secret-token\n")
    assert result.exit_code == 0
    saved = (tmp_path / "secrets.toml").read_text()
    assert "my-secret-token" in saved
    # arquivo gravado com permissão 600
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
    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0
    assert path.exists()
    assert "hosts.web" in path.read_text()
    # segunda vez sem --force deve falhar
    again = runner.invoke(cli.app, ["init"])
    assert again.exit_code == 1


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
