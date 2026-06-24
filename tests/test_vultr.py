from datetime import date

from vordr import vultr

INSTANCES = {
    "instances": [
        {
            "id": "abc-123",
            "label": "SimpliMEI-Core-Production",
            "date_created": "2026-05-20T12:00:00Z",
            "plan": "vc2-2c-8gb",
            "region": "sao",
        },
        {  # instância sem label cai no id
            "id": "no-label-9",
            "date_created": "2026-01-01T00:00:00Z",
            "plan": "vc2-1c-1gb",
        },
    ]
}

PLAN_COSTS = {"vc2-2c-8gb": 48.0, "vc2-1c-1gb": 5.0}


def test_parse_instances_maps_plan_cost():
    servers = vultr.parse_instances(INSTANCES, PLAN_COSTS)
    assert set(servers) == {"SimpliMEI-Core-Production", "no-label-9"}
    b = servers["SimpliMEI-Core-Production"]
    assert b.created == date(2026, 5, 20)
    assert b.cost_net == 48.0
    assert b.cost_gross == 48.0
    assert b.currency == "USD"


def test_parse_instances_unknown_plan_has_no_cost():
    servers = vultr.parse_instances(INSTANCES, {})
    assert servers["SimpliMEI-Core-Production"].cost_gross is None


def test_fetch_servers_wires_plans_and_instances(monkeypatch):
    def fake_get(url, token, timeout):
        if "plans" in url:
            return {"plans": [{"id": "vc2-2c-8gb", "monthly_cost": 48}]}
        return INSTANCES

    monkeypatch.setattr(vultr, "_get", fake_get)
    servers = vultr.fetch_servers("tok")
    assert servers["SimpliMEI-Core-Production"].cost_gross == 48.0
