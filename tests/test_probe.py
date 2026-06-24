from vordr import probe, ssh


def test_parse_kv_handles_repeats_and_blank_lines():
    text = "A=1\n\nB=two\nA=3\ngarbage line\nC=\n"
    kv = probe._parse_kv(text)
    assert kv["A"] == ["1", "3"]
    assert kv["B"] == ["two"]
    assert kv["C"] == [""]
    assert "garbage line" not in kv


SYSTEM_SAMPLE = """\
HOSTNAME=web-01
UPTIME_SECONDS=1814400
LOADAVG=0.28 0.08 0.02
CPUS=2
OS=Ubuntu 24.04.4 LTS
MEM_TOTAL_KB=3911000
MEM_AVAIL_KB=2664000
DISK_TOTAL_KB=39000000
DISK_USED_KB=8000000
DISK_PCT=22%
USERS=1
DOCKER_RUNNING=5
DOCKER_TOTAL=6
"""


def test_probe_system_parses_sample(monkeypatch):
    monkeypatch.setattr(
        ssh, "run", lambda *a, **k: ssh.SSHResult(0, SYSTEM_SAMPLE, "")
    )
    m = probe.probe_system("web")
    assert m.reachable
    assert m.hostname == "web-01"
    assert m.cpus == 2
    assert m.loadavg == (0.28, 0.08, 0.02)
    assert m.load_per_cpu == 0.14
    assert m.disk_pct == 22
    assert m.mem_used_pct == 32  # (3911000-2664000)/3911000 ≈ 31.9 -> 32
    assert m.docker_running == 5


def test_probe_system_unreachable(monkeypatch):
    def boom(*a, **k):
        raise ssh.SSHError("timeout (20s) ao contatar 'web'")

    monkeypatch.setattr(ssh, "run", boom)
    m = probe.probe_system("web")
    assert not m.reachable
    assert "timeout" in (m.error or "")


def test_probe_system_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        ssh, "run", lambda *a, **k: ssh.SSHResult(255, "", "Permission denied (publickey).")
    )
    m = probe.probe_system("web")
    assert not m.reachable
    assert "Permission denied" in (m.error or "")


SECURITY_SAMPLE = """\
USERS_NOW=2
LAST_LOGIN=root pts/0 1.2.3.4 Mon Jun 23 10:00
FAILED_LOGINS=137
PORTS=22 80 443 5432
FAIL2BAN=sshd
UPDATES=4
REBOOT_REQUIRED=1
"""


def test_probe_security_parses_sample(monkeypatch):
    monkeypatch.setattr(
        ssh, "run", lambda *a, **k: ssh.SSHResult(0, SECURITY_SAMPLE, "")
    )
    s = probe.probe_security("web")
    assert s.reachable
    assert s.users_now == 2
    assert s.failed_logins == 137
    assert s.ports == [22, 80, 443, 5432]
    assert s.fail2ban == "sshd"
    assert s.updates == 4
    assert s.reboot_required is True
    assert len(s.last_logins) == 1
