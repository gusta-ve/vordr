import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from vordr import rdap

SAMPLE = {
    "events": [
        {"eventAction": "registration", "eventDate": "2007-10-09T18:20:50Z"},
        {"eventAction": "expiration", "eventDate": "2026-10-09T18:20:50Z"},
        {"eventAction": "last changed", "eventDate": "2024-09-07T09:16:32Z"},
    ]
}


def test_parse_expiration():
    assert rdap._parse_expiration(SAMPLE) == date(2026, 10, 9)


def test_parse_expiration_missing():
    assert rdap._parse_expiration({"events": []}) is None
    assert rdap._parse_expiration({}) is None


def test_parse_expiration_bad_date():
    payload = {"events": [{"eventAction": "expiration", "eventDate": "nope"}]}
    assert rdap._parse_expiration(payload) is None


def test_domain_expiry_empty_name():
    assert rdap.domain_expiry("") is None


def test_domain_expiry_fetches_then_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls = {"n": 0}

    def fake_fetch(name, timeout):
        calls["n"] += 1
        return date(2026, 10, 9)

    monkeypatch.setattr(rdap, "_fetch", fake_fetch)

    # primeira chamada bate na "rede"
    assert rdap.domain_expiry("github.com") == date(2026, 10, 9)
    # segunda usa o cache (não chama _fetch de novo)
    assert rdap.domain_expiry("github.com") == date(2026, 10, 9)
    assert calls["n"] == 1


def test_concurrent_fetches_all_land_in_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def fake_fetch(name, timeout):
        return date(2027, 5, 15)

    monkeypatch.setattr(rdap, "_fetch", fake_fetch)
    domains = [f"dominio{i}.com" for i in range(12)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda d: rdap.domain_expiry(d), domains))

    # cache válido e com todos os domínios (nenhum clobberou o outro)
    with rdap._cache_path().open() as fh:
        cache = json.load(fh)
    assert set(cache) == set(domains)


def test_domain_expiry_network_failure_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def boom(name, timeout):
        raise OSError("sem rede")

    monkeypatch.setattr(rdap, "_fetch", boom)
    assert rdap.domain_expiry("exemplo.com") is None


def test_domain_expiry_stale_cache_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    # popula o cache com uma busca bem-sucedida
    monkeypatch.setattr(rdap, "_fetch", lambda name, timeout: date(2026, 10, 9))
    rdap.domain_expiry("exemplo.com", now=0.0)

    # rede cai e o cache está "vencido" (now muito à frente): usa o stale mesmo assim
    monkeypatch.setattr(rdap, "_fetch", lambda name, timeout: (_ for _ in ()).throw(OSError()))
    assert rdap.domain_expiry("exemplo.com", now=10**12) == date(2026, 10, 9)
