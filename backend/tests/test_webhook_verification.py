import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routers import coordinator
from app.main import app
from app.payments.paypal_client import PayPalClient

PAYPAL_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
    "paypal-transmission-id": "tx-1",
    "paypal-transmission-sig": "sig",
    "paypal-transmission-time": "2026-10-28T00:00:00Z",
}


@pytest.fixture
def live_client(monkeypatch):
    """Switch the shared coordinator out of mock mode for one test."""
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    coordinator.paypal_client.mock_mode = False
    yield coordinator.paypal_client


@pytest.mark.asyncio
async def test_webhook_refused_in_mock_mode():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/webhooks/paypal", json={"event_type": "X"})
        assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_refused_without_webhook_id(monkeypatch):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)
    coordinator.paypal_client.mock_mode = False
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/webhooks/paypal", json={"event_type": "X"})
        assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature_headers(live_client):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/webhooks/paypal", json={"event_type": "X"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_non_json_body(live_client):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/paypal", content=b"not json", headers=PAYPAL_HEADERS
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_processed_only_after_paypal_verifies(live_client, monkeypatch):
    seen = {}

    async def fake_verify(self, headers, event, webhook_id):
        seen["webhook_id"] = webhook_id
        return True

    monkeypatch.setattr(PayPalClient, "verify_webhook_signature", fake_verify)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/paypal",
            json={"event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "NOPE"}},
            headers=PAYPAL_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processed"
        assert seen["webhook_id"] == "WH-TEST"


@pytest.mark.asyncio
async def test_verify_never_succeeds_in_mock_mode():
    client = PayPalClient(mock_mode=True)
    assert not await client.verify_webhook_signature(PAYPAL_HEADERS, {}, "WH-TEST")


@pytest.mark.asyncio
async def test_verify_fails_closed_on_missing_header():
    client = PayPalClient(client_id="id", client_secret="secret", mock_mode=False)
    partial = {
        k: v for k, v in PAYPAL_HEADERS.items() if k != "paypal-transmission-sig"
    }
    assert not await client.verify_webhook_signature(partial, {}, "WH-TEST")
