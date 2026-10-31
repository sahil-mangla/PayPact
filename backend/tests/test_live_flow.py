"""The live-sandbox request flow, end to end, against a fake PayPal served over httpx.MockTransport."""

import json
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routers import coordinator
from app.main import app
from app.payments import paypal_client as paypal_module

PROMPT = "Find a mechanical keyboard under ₹5,000, auto-buy under ₹4,000"


class FakePayPal:
    """Just enough of Orders v2 and webhook verification to drive the app."""

    def __init__(self):
        self.orders = {}
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, request.headers.get("PayPal-Request-Id")))
        if path == "/v2/checkout/orders" and request.method == "POST":
            payload = json.loads(request.content)
            order_id = f"LIVE-ORD-{uuid.uuid4().hex[:10].upper()}"
            self.orders[order_id] = payload["purchase_units"][0]["amount"]
            return httpx.Response(201, json={"id": order_id, "status": "CREATED", "links": []})
        if path.endswith("/capture"):
            order_id = path.split("/")[-2]
            amount = self.orders[order_id]
            return httpx.Response(
                201,
                json={
                    "id": order_id,
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": f"CAP-{order_id}",
                                        "amount": {
                                            "currency_code": amount["currency_code"],
                                            "value": amount["value"],
                                        },
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})


@pytest.fixture
def fake_paypal(monkeypatch):
    fake = FakePayPal()
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(paypal_module.httpx, "AsyncClient", factory)
    client = paypal_module.PayPalClient(
        client_id="id",
        client_secret="secret",
        base_url="https://api-m.sandbox.paypal.test",
        mock_mode=False,
    )
    client._access_token = "tok"
    client._token_expires_at = 10**12
    monkeypatch.setattr(coordinator, "paypal_client", client)
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    return fake


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _authorized_checkout(client: AsyncClient) -> str:
    intent = (
        await client.post("/api/authorizations/parse-intent", json={"prompt": PROMPT})
    ).json()
    policy = (await client.post("/api/authorizations", json=intent)).json()
    proposal = (
        await client.post(
            "/api/proposals",
            json={
                "prompt": "Keychron K2 wireless mechanical keyboard",
                "policy_id": policy["policy_id"],
            },
        )
    ).json()
    assert proposal["state"] == "AUTHORIZED"
    return proposal["checkout_id"]


@pytest.mark.asyncio
async def test_create_approve_capture_and_refund_against_live_paypal(fake_paypal):
    async with _api() as client:
        checkout_id = await _authorized_checkout(client)

        execute = (await client.post(f"/api/checkouts/{checkout_id}/execute", json={})).json()
        assert execute["paypal_mode"] == "live_sandbox"
        assert execute["needs_buyer_approval"] is True
        order_id = execute["paypal_order_id"]
        assert order_id.startswith("LIVE-ORD-")
        # INR is not a PayPal sandbox currency, so the order is created in USD.
        assert fake_paypal.orders[order_id]["currency_code"] == "USD"

        # Closing and reopening the popup asks for the order again; no second order appears.
        again = (await client.post(f"/api/checkouts/{checkout_id}/execute", json={})).json()
        assert again["paypal_order_id"] == order_id
        assert len(fake_paypal.orders) == 1

        capture = await client.post(
            f"/api/checkouts/{checkout_id}/capture", json={"paypal_order_id": order_id}
        )
        session = capture.json()["session"]
        assert session["state"] == "PAID"
        assert session["paypal_capture_id"] == f"CAP-{order_id}"
        policy_id = session["policy_id"]
        spent = (await client.get(f"/api/authorizations/{policy_id}")).json()["spent_total"]
        assert spent == session["proposal"]["total_amount"]

        # A real PayPal refund event names the refund id; the order is in related_ids.
        event = {
            "id": "WH-EVT-1",
            "event_type": "PAYMENT.CAPTURE.REFUNDED",
            "resource": {
                "id": "REFUND-1",
                "amount": {"value": "5.00", "currency_code": "USD"},
                "supplementary_data": {"related_ids": {"order_id": order_id}},
            },
        }
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
            "paypal-transmission-id": "tid",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "2026-10-31T00:00:00Z",
        }
        first = await client.post("/api/webhooks/paypal", json=event, headers=headers)
        replay = await client.post("/api/webhooks/paypal", json=event, headers=headers)
        assert first.status_code == replay.status_code == 200
        assert first.json()["updated_checkout"] == checkout_id

        after = (await client.get(f"/api/authorizations/{policy_id}")).json()["spent_total"]
        # USD 5.00 of the USD charge comes back as the same share of the INR budget, once:
        # the replay must not credit it a second time.
        charged_usd = float(fake_paypal.orders[order_id]["value"])
        expected_credit = round(5.0 / charged_usd * session["proposal"]["total_amount"], 2)
        assert after == round(spent - expected_credit, 2)


@pytest.mark.asyncio
async def test_capture_after_revocation_is_blocked_and_never_reaches_paypal(fake_paypal):
    async with _api() as client:
        checkout_id = await _authorized_checkout(client)
        execute = (await client.post(f"/api/checkouts/{checkout_id}/execute", json={})).json()
        order_id = execute["paypal_order_id"]
        policy_id = execute["session"]["policy_id"]

        await client.post(f"/api/authorizations/{policy_id}/revoke")
        capture = (
            await client.post(
                f"/api/checkouts/{checkout_id}/capture", json={"paypal_order_id": order_id}
            )
        ).json()

        assert capture["session"]["state"] == "POLICY_REJECTED"
        assert not any(path.endswith("/capture") for _, path, _ in fake_paypal.calls)


@pytest.mark.asyncio
async def test_every_mutating_paypal_call_carries_an_idempotency_key(fake_paypal):
    async with _api() as client:
        checkout_id = await _authorized_checkout(client)
        order_id = (
            await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        ).json()["paypal_order_id"]
        await client.post(f"/api/checkouts/{checkout_id}/capture", json={"paypal_order_id": order_id})

    mutating = [c for c in fake_paypal.calls if c[0] == "POST" and "/v2/checkout/orders" in c[1]]
    assert len(mutating) == 2
    assert all(request_id for _, _, request_id in mutating)
    assert mutating[1][2].endswith("_cap")


def _webhook_headers():
    return {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
        "paypal-transmission-id": "tid",
        "paypal-transmission-sig": "sig",
        "paypal-transmission-time": "2026-10-31T00:00:00Z",
    }


def _refund_event(event_id, order_id, value, currency="USD"):
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {
            "id": f"REFUND-{event_id}",
            "amount": {"value": value, "currency_code": currency},
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }


@pytest.mark.asyncio
async def test_refund_reported_in_usd_is_converted_back_to_the_budget_currency(fake_paypal):
    """The sandbox charge is in USD, but the budget is tracked in the proposal's INR."""
    async with _api() as client:
        checkout_id = await _authorized_checkout(client)
        order_id = (
            await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        ).json()["paypal_order_id"]
        session = (
            await client.post(
                f"/api/checkouts/{checkout_id}/capture", json={"paypal_order_id": order_id}
            )
        ).json()["session"]
        policy_id = session["policy_id"]
        total_inr = session["proposal"]["total_amount"]
        charged_usd = float(fake_paypal.orders[order_id]["value"])

        # Half the USD charge back: half of the INR budget returns, and the checkout stays PAID.
        half = f"{charged_usd / 2:.2f}"
        resp = await client.post(
            "/api/webhooks/paypal",
            json=_refund_event("WH-HALF", order_id, half),
            headers=_webhook_headers(),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["updated_checkout"] == checkout_id
        spent = (await client.get(f"/api/authorizations/{policy_id}")).json()["spent_total"]
        assert spent == pytest.approx(total_inr / 2, abs=total_inr * 0.01)
        assert (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"] == "PAID"

        # The rest comes back: fully refunded, budget fully restored.
        rest = f"{charged_usd - float(half):.2f}"
        await client.post(
            "/api/webhooks/paypal",
            json=_refund_event("WH-REST", order_id, rest),
            headers=_webhook_headers(),
        )
        assert (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"] == "REFUNDED"
        assert (await client.get(f"/api/authorizations/{policy_id}")).json()["spent_total"] == 0


@pytest.mark.asyncio
async def test_refund_in_an_unexpected_currency_is_ignored(fake_paypal):
    async with _api() as client:
        checkout_id = await _authorized_checkout(client)
        order_id = (
            await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        ).json()["paypal_order_id"]
        session = (
            await client.post(
                f"/api/checkouts/{checkout_id}/capture", json={"paypal_order_id": order_id}
            )
        ).json()["session"]
        before = (await client.get(f"/api/authorizations/{session['policy_id']}")).json()["spent_total"]

        await client.post(
            "/api/webhooks/paypal",
            json=_refund_event("WH-EUR", order_id, "10.00", currency="EUR"),
            headers=_webhook_headers(),
        )
        after = (await client.get(f"/api/authorizations/{session['policy_id']}")).json()["spent_total"]
        assert after == before
