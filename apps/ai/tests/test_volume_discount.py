"""Volume discount: the ERP decides the percentage; the agent can neither invent nor exceed it."""

import json

import httpx
import pytest

from app.tools import TOOLS, ErpClient, ToolContext

OFFER = {"eligible": True, "pct": 5.0, "unitPrice": 8.93, "listUnitPrice": 9.4, "saved": 940.0, "needsManager": False,
         "maxPct": 5.0, "manager": "Jean-Marc", "condition": "pour cette commande, livrée en une fois", "reason": "volume"}  # fmt: skip
ORDER = {"id": "ord_1", "number": "CMD-2026-000001", "clientId": "cli_0027", "status": "draft", "deliveryDate": "2026-11-28",
         "lines": [{"id": "lin_1", "productId": "prd_0001", "productName": "Reblochon de Savoie AOP fermier", "qty": 2000, "unit": "piece", "unitPrice": 9.4}],
         "totalHt": 18800.0}  # fmt: skip


@pytest.fixture
def erp(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, dict(req.url.params), json.loads(req.content or b"null")))
        if req.url.path == "/api/prices/volume-offer":
            asked = float(req.url.params.get("requestedPct") or 0)
            return httpx.Response(200, json={**OFFER, "needsManager": asked > 5})
        if req.method == "PATCH":
            body = json.loads(req.content)
            return httpx.Response(200, json={**ORDER, "lines": [{**ORDER["lines"][0], **body}]})
        if req.url.path.startswith("/api/orders/"):
            return httpx.Response(200, json=ORDER)
        if req.url.path == "/api/meta":
            return httpx.Response(200, json={"today": "2026-11-24"})
        return httpx.Response(200, json=[])

    async def today():
        return "2026-11-24"

    monkeypatch.setattr("app.tools.voice._today", today)
    client = ErpClient("voice_agent", base_url="http://erp", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return ToolContext(erp=client, actor="voice_agent"), calls


async def test_proposal_says_the_erp_offer_and_the_manager_above_the_limit(erp):
    ctx, calls = erp
    r = await TOOLS["propose_volume_discount"].run({"clientId": "cli_0027", "productId": "prd_0001", "qty": 2000, "unit": "piece", "requestedPct": 10}, ctx)
    assert r["pct"] == 5.0 and r["needsManager"]
    assert "cinq pour cent" in r["say"] and "la pièce" in r["say"] and "Jean-Marc" in r["say"]
    assert not any(m != "GET" for m, *_ in calls)  # a proposal never writes
    assert "cost" not in json.dumps(r) and "marg" not in json.dumps(r)


async def test_apply_refuses_more_than_allowed(erp):
    ctx, calls = erp
    with pytest.raises(Exception, match="au plus 5"):
        await TOOLS["apply_volume_discount"].run({"orderId": "ord_1", "productId": "prd_0001", "pct": 10}, ctx)
    assert not any(m == "PATCH" for m, *_ in calls)


async def test_apply_writes_the_erp_price_not_the_model_one(erp):
    ctx, calls = erp
    await TOOLS["apply_volume_discount"].run({"orderId": "ord_1", "productId": "prd_0001", "pct": 5}, ctx)
    (patch,) = [c for c in calls if c[0] == "PATCH"]
    assert patch[1] == "/api/orders/ord_1/lines/lin_1" and patch[3] == {"unitPrice": 8.93}


def test_discount_is_a_write_for_the_guards():
    from app.agent.guardrails import ORDER_WRITES, is_mutation
    from app.services.customer_text import WRITE_TOOLS

    assert is_mutation("apply_volume_discount") and "apply_volume_discount" in ORDER_WRITES and "apply_volume_discount" in WRITE_TOOLS
