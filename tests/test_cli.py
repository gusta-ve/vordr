from typer.testing import CliRunner

from vordr import cli
from vordr.probe import SystemMetrics

runner = CliRunner()


_SAMPLE_CONFIG = """\
[hosts.web]
ssh = "web"
label = "Web"

[hosts.db]
ssh = "db"
label = "DB"
"""


def _write_config(monkeypatch, tmp_path):
    """Escreve um config genérico e aponta o Vordr para ele (sem tocar no do usuário)."""
    path = tmp_path / "config.toml"
    path.write_text(_SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
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


def test_cost_runs_without_ssh(monkeypatch, tmp_path):
    _write_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    assert "custo" in result.stdout.lower()


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
