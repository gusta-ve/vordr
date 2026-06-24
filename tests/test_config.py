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
                "server": {
                    "provider": "Hetzner",
                    "since": "2024-03-01",
                    "expires": "2026-08-15",
                    "cost": 6.99,
                    "currency": "USD",
                    "cycle": "monthly",
                },
                "domain": {
                    "name": "alpha.example.com",
                    "registrar": "Cloudflare",
                    "expires": "2027-03-01",
                    "cost": 12.00,
                    "currency": "USD",
                    "cycle": "yearly",
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
    assert host.server.provider == "Hetzner"
    assert host.server.since == date(2024, 3, 1)
    assert host.server.expires == date(2026, 8, 15)
    assert host.server.monthly_cost == 6.99
    # domínio: registrar vira provider; custo anual normalizado para o mês
    assert host.domain is not None
    assert host.domain.name == "alpha.example.com"
    assert host.domain.provider == "Cloudflare"
    assert host.domain.monthly_cost == 1.0


def test_billing_block_still_accepted_as_server():
    c = cfg.parse({"hosts": {"legacy": {"billing": {"expires": "2026-08-15"}}}})
    assert c.host("legacy").server.expires == date(2026, 8, 15)


def test_no_domain_block_means_none():
    c = cfg.parse({"hosts": {"box": {"server": {"expires": "2026-08-15"}}}})
    assert c.host("box").domain is None


def test_yearly_cost_is_normalized_to_month():
    s = cfg.Subscription(cost=120.0, cycle="yearly")
    assert s.monthly_cost == 10.0


def test_days_left_computation():
    s = cfg.Subscription(expires=date(2026, 6, 30))
    assert s.days_left(date(2026, 6, 23)) == 7
    assert s.days_left(date(2026, 7, 1)) == -1


def test_age_days_from_since():
    s = cfg.Subscription(since=date(2024, 3, 1))
    assert s.age_days(date(2025, 3, 1)) == 365
    assert cfg.Subscription().age_days(date(2025, 3, 1)) is None


def test_ssh_defaults_to_host_name_when_absent():
    c = cfg.parse({"hosts": {"box": {}}})
    assert c.host("box").ssh == "box"


def test_invalid_date_raises():
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"hosts": {"x": {"server": {"expires": "15/08/2026"}}}})


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
        '[hosts.box]\nssh = "box"\n[hosts.box.server]\nexpires = "2026-12-01"\n',
        encoding="utf-8",
    )
    c = cfg.load(p)
    assert c.source == p
    assert c.host("box").server.expires == date(2026, 12, 1)
