from datetime import date

from typer.testing import CliRunner

from vordr import cli
from vordr.config import Config, Host, Subscription
from vordr.probe import SystemMetrics
from vordr.providers import AccountBilling

runner = CliRunner()
TODAY = date(2026, 6, 25)


def _config(**kw):
    return Config(hosts={}, runway_days=14, charge_days=7, **kw)


def test_evaluate_clear_when_nothing_crosses():
    h = Host(name="web", ssh="web", server=Subscription(provider="Hetzner"))
    alerts = cli._evaluate_alerts([(h, cli._Lifecycle())], {}, {"web": True}, _config(), TODAY)
    assert alerts == []


def test_evaluate_offline_is_critical():
    h = Host(name="web", ssh="web", server=Subscription(provider="Hetzner"))
    alerts = cli._evaluate_alerts([(h, cli._Lifecycle())], {}, {"web": False}, _config(), TODAY)
    assert any(a.crit and "offline" in a.text for a in alerts)


def test_evaluate_runway_alert_for_prepaid_bonus():
    # net credit 20, burn 60/mo -> ~10 days of runway (<= 14) -> warn, not critical
    h = Host(name="db", ssh="", server=Subscription(provider="Vultr"))
    lc = cli._Lifecycle(cost=60.0, currency="USD")
    acct = AccountBilling(balance=-20.0, pending_charges=0.0)
    alerts = cli._evaluate_alerts([(h, lc)], {"vultr": acct}, {}, _config(), TODAY)
    assert len(alerts) == 1
    assert not alerts[0].crit
    assert "credit runs out" in alerts[0].text
    assert "card charges begin" in alerts[0].text


def test_evaluate_server_and_domain_expiry():
    h = Host(
        name="web", ssh="web",
        server=Subscription(provider="DigitalOcean", expires=date(2026, 6, 30)),
    )
    lc = cli._Lifecycle(domain_expiry=date(2026, 6, 27))
    alerts = cli._evaluate_alerts([(h, lc)], {}, {"web": True}, _config(), TODAY)
    txt = " | ".join(a.text for a in alerts)
    assert "server renews in 5d" in txt
    assert "domain expires in 2d" in txt


def test_check_all_clear_exits_zero(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[thresholds]\nwarn_days = 14\n", encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0
    assert "all clear" in result.stdout.lower()


def test_check_offline_exits_nonzero(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.web]\nssh = "web"\n  [hosts.web.server]\n  provider = "Hetzner"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    monkeypatch.setattr(
        cli, "probe_system",
        lambda a, timeout=20: SystemMetrics(reachable=False, error="down"),
    )
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "offline" in result.stdout.lower()
