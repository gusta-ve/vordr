from datetime import date

import pytest
from clihelper import CliRunner

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


def test_upsert_sections_preserves_rest(tmp_path):
    import tomllib

    p = tmp_path / "config.toml"
    p.write_text('[hosts.web]\nssh = "web"\n\n[notify]\nntfy = "old"\n', encoding="utf-8")
    cli._upsert_sections(p, {
        "alerts": {"runway_days": 30, "charge_days": 5},
        "notify": {"ntfy": "https://ntfy.sh/new"},
    })
    data = tomllib.loads(p.read_text())
    assert data["hosts"]["web"]["ssh"] == "web"               # preserved
    assert data["notify"]["ntfy"] == "https://ntfy.sh/new"    # replaced, not duplicated
    assert data["alerts"] == {"runway_days": 30, "charge_days": 5}


def test_setup_writes_config(monkeypatch, tmp_path):
    import tomllib

    path = tmp_path / "config.toml"
    path.write_text('[hosts.web]\nssh = "web"\n', encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda x: None)   # no systemd branch
    # channel "ntfy" (new) / topic(enter=default) / runway "20" / charge(enter=7)
    result = runner.invoke(cli.app, ["setup"], input="ntfy\n\n20\n\n")
    assert result.exit_code == 0
    data = tomllib.loads(path.read_text())
    assert data["alerts"]["runway_days"] == 20
    assert data["alerts"]["charge_days"] == 7
    assert "ntfy" in data["notify"]
    assert data["hosts"]["web"]["ssh"] == "web"               # untouched
    # no systemd here -> nothing scheduled -> the loud warning must show
    assert "nothing is scheduled" in result.stdout.lower()


def test_setup_schedules_by_default(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[hosts.web]\nssh = "web"\n', encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda x: f"/usr/bin/{x}")   # systemd present
    installed = {}
    monkeypatch.setattr(cli, "_install_user_timer",
                        lambda b: installed.setdefault("done", True))
    # channel ntfy (new) / topic / runway / charge / schedule (enter = default YES)
    result = runner.invoke(cli.app, ["setup"], input="ntfy\n\n\n\n\n")
    assert result.exit_code == 0
    assert installed.get("done") is True                      # enter alone scheduled it
    assert "enabled vordr-check.timer" in result.stdout
    assert "nothing is scheduled" not in result.stdout.lower()


def test_setup_test_existing_channel_skips_token_reentry(monkeypatch, tmp_path):
    # naming an already-configured channel offers a test of it — never asks for the token again
    path = tmp_path / "config.toml"
    path.write_text('[hosts.web]\nssh = "web"\n[notify]\ntelegram_chat = "555"\n',
                    encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda x: None)   # no systemd branch
    monkeypatch.setattr(cli.secrets, "get_token",
                        lambda p: "123:ABC" if p == "telegram" else None)
    sent = {}

    def fake_send(title, body, **k):
        sent["title"] = title
        return ["telegram"]

    monkeypatch.setattr(cli.notify, "send", fake_send)
    # pick "telegram" (already set) / "send it a test?" enter(=yes) / runway / charge
    result = runner.invoke(cli.app, ["setup"], input="telegram\n\n\n\n")
    assert result.exit_code == 0
    assert "already configured: telegram" in result.stdout
    assert "API token" not in result.stdout                     # never re-asked the token
    assert sent.get("title") == "vordr · test notification"     # tested the kept creds


def test_setup_keep_leaves_channels_untouched(monkeypatch, tmp_path):
    # enter alone keeps everything and does NOT push anything
    path = tmp_path / "config.toml"
    path.write_text('[hosts.web]\nssh = "web"\n[notify]\ntelegram_chat = "555"\n',
                    encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda x: None)
    monkeypatch.setattr(cli.secrets, "get_token",
                        lambda p: "123:ABC" if p == "telegram" else None)
    monkeypatch.setattr(cli.notify, "send",
                        lambda *a, **k: pytest.fail("keep must not push"))
    # enter=keep / runway / charge
    result = runner.invoke(cli.app, ["setup"], input="\n\n\n")
    assert result.exit_code == 0
    assert "vordr test" in result.stdout       # points at the dedicated test command


def test_test_command_pushes_sample(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[notify]\ntelegram_chat = "555"\n', encoding="utf-8")
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli.secrets, "get_token",
                        lambda p: "123:ABC" if p == "telegram" else None)
    captured = {}

    def fake_send(title, body, **k):
        captured["title"], captured["body"] = title, body
        return ["telegram"]

    monkeypatch.setattr(cli.notify, "send", fake_send)
    result = runner.invoke(cli.app, ["test"])
    assert result.exit_code == 0
    assert captured["title"] == "vordr · test notification"
    # the body shows the real layout — a bracket-tag per item
    assert "[!!]" in captured["body"] and "[!]" in captured["body"] and "[+]" in captured["body"]


def test_merge_notes_dedups_preserving_order():
    # the server and account fetchers both report the same provider error
    merged = cli._merge_notes(
        ["vultr: HTTP 401", "hetzner: no token"],
        ["vultr: HTTP 401"],
    )
    assert merged == ["vultr: HTTP 401", "hetzner: no token"]


def test_probe_reachability_retries_transient_failure(monkeypatch):
    # a host that fails the first probe but answers the retry must NOT be flagged offline
    h = Host(name="web", ssh="web", server=Subscription(provider="Hetzner"))
    calls = {"web": 0}

    def fake_probe(alias, timeout=20):
        calls[alias] += 1
        return SystemMetrics(reachable=calls[alias] >= 2)

    monkeypatch.setattr(cli, "probe_system", fake_probe)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    reach = cli._probe_reachability([h], timeout=5)
    assert reach == {"web": True}
    assert calls["web"] == 2  # probed once, retried once


def test_probe_reachability_reports_down_after_retries(monkeypatch):
    h = Host(name="web", ssh="web", server=Subscription(provider="Hetzner"))
    monkeypatch.setattr(cli, "probe_system", lambda a, timeout=20: SystemMetrics(reachable=False))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    reach = cli._probe_reachability([h], timeout=5, retries=2)
    assert reach == {"web": False}


def test_parse_interval():
    assert cli._parse_interval("30m") == 1800
    assert cli._parse_interval("6h") == 21600
    assert cli._parse_interval("1d") == 86400
    assert cli._parse_interval("45") == 45        # bare seconds
    assert cli._parse_interval("0") == 1          # clamped to >= 1


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
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)  # don't wait on the retry
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "offline" in result.stdout.lower()


def test_urgency_tier():
    assert cli._urgency_tier(7) == 1
    assert cli._urgency_tier(2) == 1
    assert cli._urgency_tier(1) == 2     # imminent
    assert cli._urgency_tier(0) == 3     # due
    assert cli._urgency_tier(-3) == 3    # overdue


def test_select_to_push_new_then_silent_then_escalation():
    a1 = cli._Alert(False, "Hetzner", "charge in 7d", key="hetzner:charge", tier=1)
    push, state = cli._select_to_push([a1], {})
    assert [a.key for a in push] == ["hetzner:charge"]   # brand new -> pushed
    assert state == {"hetzner:charge": 1}

    push, state = cli._select_to_push([a1], state)        # same tier -> silent
    assert push == []
    assert state == {"hetzner:charge": 1}

    a2 = cli._Alert(False, "Hetzner", "charge in 1d", key="hetzner:charge", tier=2)
    push, state = cli._select_to_push([a2], state)        # climbed -> pushed again
    assert [a.key for a in push] == ["hetzner:charge"]
    assert state == {"hetzner:charge": 2}


def test_select_to_push_drops_cleared_alert():
    state = {"web:offline": 3, "hetzner:charge": 1}
    a = cli._Alert(False, "Hetzner", "charge in 5d", key="hetzner:charge", tier=1)
    push, new_state = cli._select_to_push([a], state)
    assert push == []                          # already pushed at tier 1
    assert new_state == {"hetzner:charge": 1}  # web:offline cleared -> dropped


def test_notify_state_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "state.json"
    monkeypatch.setenv("VORDR_NOTIFY_STATE", str(p))
    cli._save_notify_state({"a:b": 2})
    assert cli._load_notify_state() == {"a:b": 2}
    p.write_text("not json", encoding="utf-8")   # corrupt -> empty, no crash
    assert cli._load_notify_state() == {}


def test_check_notify_dedups_repeat(monkeypatch, tmp_path):
    # a server whose renewal is long overdue -> a standing alert on every run
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = ""\n  [hosts.box.server]\n'
        '  provider = "Hetzner"\n  expires = "2000-01-01"\n'
        '[notify]\nntfy = "https://ntfy.sh/x"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_NOTIFY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    monkeypatch.setattr(cli, "_resolve_domain_expiries", lambda *a, **k: {})
    sent: list[int] = []
    monkeypatch.setattr(cli.notify, "send", lambda *a, **k: (sent.append(1) or ["ntfy"]))

    r1 = runner.invoke(cli.app, ["check", "--notify"])    # new alert -> push
    r2 = runner.invoke(cli.app, ["check", "--notify"])    # same alert -> quiet
    assert r1.exit_code == 1 and r2.exit_code == 1
    assert len(sent) == 1                                  # pushed once, deduped the repeat
    assert "no change since last push" in r2.stdout.lower()


def test_check_notify_routes_to_telegram(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = ""\n  [hosts.box.server]\n'
        '  provider = "Hetzner"\n  expires = "2000-01-01"\n'
        '[notify]\ntelegram_chat = "555"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_NOTIFY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setenv("VORDR_TELEGRAM_TOKEN", "123:ABC")   # token via env
    monkeypatch.setattr(cli, "_resolve_domain_expiries", lambda *a, **k: {})
    captured = {}

    def fake_send(title, body, *, ntfy=None, telegram=None, email=None, critical=False, timeout=10):
        captured["telegram"] = telegram
        return ["telegram"] if telegram else []

    monkeypatch.setattr(cli.notify, "send", fake_send)
    result = runner.invoke(cli.app, ["check", "--notify"])
    assert result.exit_code == 1
    assert captured["telegram"] == ("123:ABC", "555")   # token + chat passed through


def test_check_notify_fires_telegram_and_email_together(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = ""\n  [hosts.box.server]\n'
        '  provider = "Hetzner"\n  expires = "2000-01-01"\n'
        '[notify]\ntelegram_chat = "555"\nemail = "me@gmail.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_NOTIFY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setenv("VORDR_TELEGRAM_TOKEN", "123:ABC")
    monkeypatch.setenv("VORDR_EMAIL_PASSWORD", "app-pw")
    monkeypatch.setattr(cli, "_resolve_domain_expiries", lambda *a, **k: {})
    captured = {}

    def fake_send(title, body, *, ntfy=None, telegram=None, email=None, critical=False, timeout=10):
        captured["telegram"], captured["email"] = telegram, email
        return [c for c, v in (("telegram", telegram), ("email", email)) if v]

    monkeypatch.setattr(cli.notify, "send", fake_send)
    result = runner.invoke(cli.app, ["check", "--notify"])
    assert result.exit_code == 1
    assert captured["telegram"] == ("123:ABC", "555")
    assert captured["email"] == cli.notify.EmailTarget(
        "smtp.gmail.com", 587, "me@gmail.com", "app-pw", "me@gmail.com")


def test_recovered_offline_only_for_offline_keys():
    state = {"web:offline": 3, "hetzner:charge": 1}
    rec = cli._recovered_offline([], state, {"web": "Web"})
    assert [(a.who, a.text, a.tier) for a in rec] == [("Web", "back online", 0)]
    # a charge clearing is NOT a recovery; an offline that still stands is NOT either
    still = cli._Alert(True, "Web", "offline (unreachable)", key="web:offline", tier=3)
    assert cli._recovered_offline([still], state, {"web": "Web"}) == []


def test_check_notify_offline_then_recovery(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts.box]\nssh = "box"\n  [hosts.box.server]\n  provider = "Hetzner"\n'
        '[notify]\nntfy = "https://ntfy.sh/x"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VORDR_CONFIG", str(path))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("VORDR_NOTIFY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VORDR_SECRETS", str(tmp_path / "secrets.toml"))
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.setattr(cli.secrets, "get_token", lambda p: None)
    monkeypatch.setattr(cli, "_resolve_domain_expiries", lambda *a, **k: {})
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    bodies: list[str] = []

    def fake_send(title, body, **k):
        bodies.append(body)
        return ["ntfy"]

    monkeypatch.setattr(cli.notify, "send", fake_send)

    reachable = {"v": False}
    monkeypatch.setattr(
        cli, "probe_system", lambda a, timeout=20: SystemMetrics(reachable=reachable["v"])
    )

    r1 = runner.invoke(cli.app, ["check", "--notify"])    # offline -> push
    reachable["v"] = True
    runner.invoke(cli.app, ["check", "--notify"])         # back online -> recovery push
    r3 = runner.invoke(cli.app, ["check", "--notify"])    # clear, ledger empty -> nothing

    assert r1.exit_code == 1 and r3.exit_code == 0
    assert len(bodies) == 2
    assert "offline" in bodies[0].lower()
    assert "back online" in bodies[1].lower()
