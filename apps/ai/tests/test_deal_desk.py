"""« Le comité de prix »: two options to the caller, nothing confidential to the model, only ERP-checked values written."""

import json

import httpx
import pytest

from app.services import deal_desk
from app.tools import TOOLS, ErpClient, ToolContext

OPTS = {
    "A": {"key": "A", "qty": 200.0, "unit": "piece", "pct": 0.0, "unitPrice": 7.2, "listUnitPrice": 7.2, "total": 1440.0,
          "margin": 350.0, "wasteAvoided": 0.0, "pAccept": 0.35, "expected": 122.5, "why": "prix habituel"},
    "C": {"key": "C", "qty": 300.0, "unit": "piece", "pct": 3.0, "unitPrice": 6.98, "listUnitPrice": 7.2, "total": 2094.0,
          "margin": 459.0, "wasteAvoided": 545.0, "pAccept": 0.42, "expected": 421.68, "why": "écouler un lot à date courte"},
}  # fmt: skip
ORDER = {"id": "ord_1", "number": "CMD-2026-000001", "clientId": "cli_0027", "status": "draft", "deliveryDate": "2026-11-28",
         "lines": [{"id": "lin_1", "productId": "prd_0002", "productName": "Reblochon laitier", "qty": 200, "unit": "piece", "unitPrice": 7.2}],
         "totalHt": 1440.0}  # fmt: skip


@pytest.fixture
def ctx(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content or b"null")))
        if req.url.path == "/api/prices/deal-options":
            return httpx.Response(200, json={"options": list(OPTS.values()), "chosen": "C", "alternative": "A"})
        if req.method == "PATCH":
            return httpx.Response(200, json={**ORDER, "lines": [{**ORDER["lines"][0], **json.loads(req.content)}]})
        if req.url.path.startswith("/api/orders/"):
            return httpx.Response(200, json=ORDER)
        return httpx.Response(200, json={"today": "2026-11-24"})

    async def today():
        return "2026-11-24"

    async def fake_run(erp, client_id, product_id, qty, delivery_date=None, objection=True):
        panel = {"dealId": "d1", "chosen": "C", "alternative": "A", "agents": [], "options": list(OPTS.values()), "decision": "C"}
        deal_desk.DEALS["d1"] = {"panel": panel, "negotiatedCost": None, "sourcingId": None, "clientId": client_id,
                                 "productId": product_id, "qty": qty, "options": OPTS, "blocked": None}  # fmt: skip
        return deal_desk.DEALS["d1"]

    monkeypatch.setattr("app.tools.voice._today", today)
    monkeypatch.setattr(deal_desk, "run", fake_run)
    client = ErpClient("voice_agent", base_url="http://erp", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return ToolContext(erp=client, actor="voice_agent"), calls


async def test_two_options_and_nothing_confidential_for_the_model(ctx):
    c, calls = ctx
    r = await TOOLS["propose_deal"].run({"clientId": "cli_0027", "productId": "prd_0002", "qty": 200}, c)
    assert [o["key"] for o in r["options"]] == ["A", "C"]  # smaller quantity first
    assert "trois cents" in r["say"] and "Lequel" in r["say"]
    dumped = json.dumps(r)
    assert not any(k in dumped for k in ("margin", "wasteAvoided", "expected", "pAccept", "cost"))
    assert not any(m != "GET" for m, *_ in calls)  # a proposal writes nothing


async def test_apply_writes_the_erp_recomputed_option(ctx):
    c, calls = ctx
    await TOOLS["propose_deal"].run({"clientId": "cli_0027", "productId": "prd_0002", "qty": 200}, c)
    await TOOLS["apply_deal"].run({"orderId": "ord_1", "dealId": "d1", "option": "c"}, c)
    (patch,) = [x for x in calls if x[0] == "PATCH"]
    assert patch[1] == "/api/orders/ord_1/lines/lin_1" and patch[2] == {"qty": 300.0, "unitPrice": 6.98}


async def test_unknown_option_or_deal_is_refused(ctx):
    c, _ = ctx
    await TOOLS["propose_deal"].run({"clientId": "cli_0027", "productId": "prd_0002", "qty": 200}, c)
    with pytest.raises(Exception, match="indisponible"):
        await TOOLS["apply_deal"].run({"orderId": "ord_1", "dealId": "d1", "option": "Z"}, c)
    with pytest.raises(Exception, match="expirée"):
        await TOOLS["apply_deal"].run({"orderId": "ord_1", "dealId": "nope", "option": "C"}, c)


def test_apply_deal_is_a_write_for_every_guard():
    from app.agent.guardrails import ORDER_WRITES, is_mutation
    from app.services.customer_text import WRITE_TOOLS
    from app.services.fast_path import RECONCILE

    assert is_mutation("apply_deal") and {"apply_deal"} <= ORDER_WRITES & WRITE_TOOLS & RECONCILE
