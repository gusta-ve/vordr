from datetime import date

import pytest

from vordr import config as cfg


def test_load_missing_file_returns_empty(tmp_path):
    c = cfg.load(tmp_path / "nope.toml")
    assert c.hosts == {}
    assert c.source is None


def test_parse_full_config():
    data = {
        "thresholds": {"warn_days": 10, "critical_days": 3},
        "hosts": {
            "alpha": {
                "ssh": "alpha-ssh",
                "label": "Alpha",
                "status_command": "alpha-status",
                "billing": {
                    "provider": "Contabo",
                    "expires": "2026-08-15",
                    "cost": 6.99,
                    "currency": "USD",
                    "cycle": "monthly",
                },
            }
        },
    }
    c = cfg.parse(data)
    assert c.warn_days == 10
    assert c.critical_days == 3
    host = c.host("alpha")
    assert host.ssh == "alpha-ssh"
    assert host.display == "Alpha"
    assert host.billing.expires == date(2026, 8, 15)
    assert host.billing.monthly_cost == 6.99


def test_yearly_cost_is_normalized_to_month():
    b = cfg.Billing(cost=120.0, cycle="yearly")
    assert b.monthly_cost == 10.0


def test_days_left_computation():
    b = cfg.Billing(expires=date(2026, 6, 30))
    assert b.days_left(date(2026, 6, 23)) == 7
    assert b.days_left(date(2026, 7, 1)) == -1


def test_ssh_defaults_to_host_name_when_absent():
    c = cfg.parse({"hosts": {"box": {}}})
    assert c.host("box").ssh == "box"


def test_invalid_date_raises():
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"hosts": {"x": {"billing": {"expires": "15/08/2026"}}}})


def test_unknown_host_raises():
    c = cfg.parse({"hosts": {"box": {}}})
    with pytest.raises(cfg.ConfigError):
        c.host("inexistente")


def test_empty_hosts_stays_empty():
    c = cfg.parse({"hosts": {}})
    assert c.hosts == {}


def test_load_reads_toml_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[hosts.box]\nssh = "box"\n[hosts.box.billing]\nexpires = "2026-12-01"\n',
        encoding="utf-8",
    )
    c = cfg.load(p)
    assert c.source == p
    assert c.host("box").billing.expires == date(2026, 12, 1)
