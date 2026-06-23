from typer.testing import CliRunner

from vordr import cli
from vordr.probe import SystemMetrics

runner = CliRunner()


def _isolate_config(monkeypatch, tmp_path):
    """Garante que os testes usem os padrões embutidos, não o config do usuário."""
    monkeypatch.setenv("VORDR_CONFIG", str(tmp_path / "absent.toml"))


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "vordr" in result.stdout


def test_hosts_lists_defaults(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["hosts"])
    assert result.exit_code == 0
    assert "nexus" in result.stdout.lower()
    assert "simplimei" in result.stdout.lower()


def test_cost_runs_without_ssh(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == 0
    assert "custo" in result.stdout.lower()


def test_init_creates_config(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0
    assert path.exists()
    assert "hosts.nexus" in path.read_text()
    # segunda vez sem --force deve falhar
    again = runner.invoke(cli.app, ["init"])
    assert again.exit_code == 1


def test_status_uses_probe(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)

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
    _isolate_config(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["status", "naoexiste"])
    assert result.exit_code == 2
