from vordr import ssh

SSH_CONFIG = """\
# my ssh config
Host web
    HostName 10.0.0.1
    User root

Host db prod-db
    HostName 10.0.0.2

Host *.internal
    User admin

Host *
    ServerAliveInterval 60
"""


def test_list_aliases_reads_hosts(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SSH_CONFIG, encoding="utf-8")
    aliases = ssh.list_aliases(cfg)
    # skip wildcard patterns (*.internal, *) and keep the order
    assert aliases == ["web", "db", "prod-db"]


def test_list_aliases_missing_file(tmp_path):
    assert ssh.list_aliases(tmp_path / "missing") == []
