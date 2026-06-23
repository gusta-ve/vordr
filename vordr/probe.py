"""Coleta de métricas estruturadas dos hosts.

Em vez de tentar parsear a saída colorida do ``nexus-status`` (frágil, cheia de
ANSI), Vordr roda pequenos scripts ``sh`` portáveis no servidor que emitem
linhas ``CHAVE=valor``. Isso é estável, fácil de testar e permite aplicar
limiares (load alto, disco cheio, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ssh

# Script de métricas de sistema. Mantido portável (POSIX sh + /proc) e tolerante
# a comandos ausentes — cada peça falha em silêncio em vez de derrubar tudo.
_SYSTEM_PROBE = r"""
echo "HOSTNAME=$(hostname 2>/dev/null)"
if [ -r /proc/uptime ]; then echo "UPTIME_SECONDS=$(cut -d. -f1 /proc/uptime)"; fi
if [ -r /proc/loadavg ]; then echo "LOADAVG=$(cut -d' ' -f1-3 /proc/loadavg)"; fi
echo "CPUS=$(nproc 2>/dev/null || echo 1)"
if [ -r /etc/os-release ]; then . /etc/os-release; echo "OS=$PRETTY_NAME"; fi
if [ -r /proc/meminfo ]; then
  awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{print "MEM_TOTAL_KB="t; print "MEM_AVAIL_KB="a}' /proc/meminfo
fi
df -P / 2>/dev/null | awk 'NR==2{print "DISK_TOTAL_KB="$2; print "DISK_USED_KB="$3; print "DISK_PCT="$5}'
echo "USERS=$(who 2>/dev/null | wc -l | tr -d ' ')"
if command -v docker >/dev/null 2>&1; then
  echo "DOCKER_RUNNING=$(docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
  echo "DOCKER_TOTAL=$(docker ps -aq 2>/dev/null | wc -l | tr -d ' ')"
fi
"""

# Script de segurança. Best-effort: usa `sudo -n` (não-interativo) e descarta
# erros, marcando como indisponível o que exigir privilégio inexistente.
_SECURITY_PROBE = r"""
echo "USERS_NOW=$(who 2>/dev/null | wc -l | tr -d ' ')"

# Últimos logins bem-sucedidos
last -n 3 2>/dev/null | grep -v '^$' | grep -vi 'wtmp begins' | head -n 3 | while IFS= read -r l; do
  echo "LAST_LOGIN=$l"
done

# Falhas de autenticação (tenta lastb com sudo -n; senão, journald)
FAILED=""
if command -v lastb >/dev/null 2>&1; then
  FAILED=$(sudo -n lastb 2>/dev/null | grep -v '^$' | grep -vi 'btmp begins' | wc -l | tr -d ' ')
fi
if [ -z "$FAILED" ] || [ "$FAILED" = "0" ]; then
  if command -v journalctl >/dev/null 2>&1; then
    J=$(sudo -n journalctl _COMM=sshd --since '24 hours ago' 2>/dev/null | grep -c 'Failed password')
    [ -n "$J" ] && FAILED="$J"
  fi
fi
[ -n "$FAILED" ] && echo "FAILED_LOGINS=$FAILED"

# Portas TCP em escuta (porta única, deduplicada)
if command -v ss >/dev/null 2>&1; then
  ss -H -ltn 2>/dev/null | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\n' ' ' | sed 's/^/PORTS=/'
  echo ""
fi

# fail2ban
if command -v fail2ban-client >/dev/null 2>&1; then
  J=$(sudo -n fail2ban-client status 2>/dev/null | grep 'Jail list' | sed 's/.*:\s*//')
  if [ -n "$J" ]; then echo "FAIL2BAN=$J"; else echo "FAIL2BAN=ativo (sem detalhe: requer sudo)"; fi
fi

# Atualizações pendentes / reboot necessário
if command -v apt-get >/dev/null 2>&1; then
  U=$(apt-get -s -o Debug::NoLocking=true upgrade 2>/dev/null | grep -c '^Inst')
  echo "UPDATES=$U"
fi
[ -f /var/run/reboot-required ] && echo "REBOOT_REQUIRED=1"
"""


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_kv(stdout: str) -> dict[str, list[str]]:
    """Converte linhas ``CHAVE=valor`` num dict; chaves repetidas viram listas."""
    out: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        out.setdefault(key, []).append(value)
    return out


@dataclass
class SystemMetrics:
    reachable: bool = False
    error: str | None = None
    hostname: str | None = None
    os: str | None = None
    uptime_seconds: int | None = None
    loadavg: tuple[float, float, float] | None = None
    cpus: int | None = None
    mem_total_kb: int | None = None
    mem_avail_kb: int | None = None
    disk_total_kb: int | None = None
    disk_used_kb: int | None = None
    disk_pct: int | None = None
    users: int | None = None
    docker_running: int | None = None
    docker_total: int | None = None

    @property
    def mem_used_pct(self) -> int | None:
        if self.mem_total_kb and self.mem_avail_kb is not None and self.mem_total_kb > 0:
            used = self.mem_total_kb - self.mem_avail_kb
            return round(used * 100 / self.mem_total_kb)
        return None

    @property
    def load1(self) -> float | None:
        return self.loadavg[0] if self.loadavg else None

    @property
    def load_per_cpu(self) -> float | None:
        if self.load1 is not None and self.cpus:
            return round(self.load1 / self.cpus, 2)
        return None


@dataclass
class SecurityMetrics:
    reachable: bool = False
    error: str | None = None
    users_now: int | None = None
    failed_logins: int | None = None
    last_logins: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    fail2ban: str | None = None
    updates: int | None = None
    reboot_required: bool = False


def _parse_loadavg(raw: str) -> tuple[float, float, float] | None:
    parts = raw.split()
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def probe_system(alias: str, *, timeout: int = ssh.DEFAULT_TIMEOUT) -> SystemMetrics:
    """Coleta métricas de sistema de um host."""
    try:
        result = ssh.run(alias, _SYSTEM_PROBE, timeout=timeout)
    except ssh.SSHError as exc:
        return SystemMetrics(reachable=False, error=str(exc))
    if not result.ok:
        msg = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "falha SSH"
        return SystemMetrics(reachable=False, error=msg)

    kv = _parse_kv(result.stdout)

    def first(key: str) -> str | None:
        values = kv.get(key)
        return values[0] if values else None

    return SystemMetrics(
        reachable=True,
        hostname=first("HOSTNAME"),
        os=first("OS"),
        uptime_seconds=_to_int(first("UPTIME_SECONDS") or ""),
        loadavg=_parse_loadavg(first("LOADAVG") or ""),
        cpus=_to_int(first("CPUS") or ""),
        mem_total_kb=_to_int(first("MEM_TOTAL_KB") or ""),
        mem_avail_kb=_to_int(first("MEM_AVAIL_KB") or ""),
        disk_total_kb=_to_int(first("DISK_TOTAL_KB") or ""),
        disk_used_kb=_to_int(first("DISK_USED_KB") or ""),
        disk_pct=_to_int((first("DISK_PCT") or "").rstrip("%")),
        users=_to_int(first("USERS") or ""),
        docker_running=_to_int(first("DOCKER_RUNNING") or ""),
        docker_total=_to_int(first("DOCKER_TOTAL") or ""),
    )


def probe_security(alias: str, *, timeout: int = ssh.DEFAULT_TIMEOUT) -> SecurityMetrics:
    """Coleta sinais de segurança de um host (best-effort, sem exigir sudo)."""
    try:
        result = ssh.run(alias, _SECURITY_PROBE, timeout=timeout)
    except ssh.SSHError as exc:
        return SecurityMetrics(reachable=False, error=str(exc))
    if not result.ok and not result.stdout.strip():
        msg = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "falha SSH"
        return SecurityMetrics(reachable=False, error=msg)

    kv = _parse_kv(result.stdout)

    def first(key: str) -> str | None:
        values = kv.get(key)
        return values[0] if values else None

    ports: list[int] = []
    if "PORTS" in kv:
        for token in (first("PORTS") or "").split():
            value = _to_int(token)
            if value is not None:
                ports.append(value)

    return SecurityMetrics(
        reachable=True,
        users_now=_to_int(first("USERS_NOW") or ""),
        failed_logins=_to_int(first("FAILED_LOGINS") or ""),
        last_logins=kv.get("LAST_LOGIN", []),
        ports=sorted(set(ports)),
        fail2ban=first("FAIL2BAN"),
        updates=_to_int(first("UPDATES") or ""),
        reboot_required="REBOOT_REQUIRED" in kv,
    )
