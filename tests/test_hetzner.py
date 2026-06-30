from datetime import date

from vordr import hetzner

PAYLOAD = {
    "servers": [
        {
            "name": "web-01",
            "created": "2026-05-19T02:40:26Z",
            "datacenter": {"location": {"name": "nbg1"}},
            "server_type": {
                "name": "cx23",
                "prices": [
                    {"location": "fsn1", "price_monthly": {"net": "5.45", "gross": "6.49"}},
                    {"location": "nbg1", "price_monthly": {"net": "5.45", "gross": "6.49"}},
                ],
            },
        }
    ]
}


def test_parse_servers_picks_location_price():
    servers = hetzner.parse_servers(PAYLOAD)
    assert set(servers) == {"web-01"}
    b = servers["web-01"]
    assert b.created == date(2026, 5, 19)
    assert b.cost_net == 5.45
    assert b.cost_gross == 6.49
    assert b.currency == "EUR"


def test_parse_created_bad():
    assert hetzner.parse_api_date(None) is None
    assert hetzner.parse_api_date("not-a-date") is None


def test_parse_servers_skips_nameless():
    servers = hetzner.parse_servers({"servers": [{"created": "2026-01-01T00:00:00Z"}]})
    assert servers == {}


def test_monthly_price_no_prices():
    net, gross = hetzner._monthly_price({"server_type": {"prices": []}})
    assert net is None and gross is None
