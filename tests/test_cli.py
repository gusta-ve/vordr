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


def _write_config(monkeypatch, tmp_path):
    """Escreve um config genérico e aponta o Vordr para ele (sem tocar no do usuário)."""
    path = tmp_path / "config.toml"
    path.write_text(_SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    # evita o rich truncar colunas na largura padrão (80) fora de um terminal
    monkeypatch.setenv("COLUMNS", "200")
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
