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
        {  # instance with no label falls back to the id
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


ACCOUNT = {
    "account": {
        "balance": -193.88,
        "pending_charges": 79.02,
        "last_payment_date": "2026-05-13T00:59:19+00:00",
        "last_payment_amount": -250,
    }
}


def test_parse_account_credit_and_pending():
    acct = vultr.parse_account(ACCOUNT)
    assert acct.balance == -193.88
    assert acct.pending_charges == 79.02
    assert acct.credit == 193.88           # negative balance becomes credit
    assert acct.net_remaining == 114.86    # credit - pending


def test_fetch_account_hits_account_endpoint(monkeypatch):
    monkeypatch.setattr(vultr, "_get", lambda url, token, timeout: ACCOUNT)
    acct = vultr.fetch_account("tok")
    assert acct.credit == 193.88


def test_postpaid_account_balance_unknown():
    from vordr.providers import AccountBilling

    assert AccountBilling().credit is None
    assert AccountBilling().net_remaining is None
