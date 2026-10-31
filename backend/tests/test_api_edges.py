"""API contract edges: unknown ids, junk inputs and error wording."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_payment_path_fixes import AUTO_PROMPT, _new_checkout


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/checkouts/chk_nope", None),
        ("get", "/api/checkouts/chk_nope/receipt", None),
        ("post", "/api/checkouts/chk_nope/approve", {}),
        ("post", "/api/checkouts/chk_nope/execute", {}),
        ("post", "/api/checkouts/chk_nope/capture", {"paypal_order_id": "ORD1"}),
        ("post", "/api/checkouts/chk_nope/reconcile", None),
    ],
)
async def test_unknown_checkout_is_a_404_everywhere(method, path, body):
    async with _client() as client:
        resp = await getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_unknown_lab_scenario_is_a_404_not_a_server_error():
    async with _client() as client:
        resp = await client.post("/api/lab/run", json={"scenario_id": "SC-ZZ"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_lab_system_type_is_rejected_instead_of_run_as_something_else():
    async with _client() as client:
        resp = await client.post(
            "/api/lab/run", json={"scenario_id": "SC-A", "system_type": "NOPE"}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_junk_drift_inputs_are_rejected():
    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        bad_type = await client.post(
            f"/api/checkouts/{checkout_id}/execute", json={"simulate_drift_type": "banana"}
        )
        assert bad_type.status_code == 422
        bad_fee = await client.post(
            f"/api/checkouts/{checkout_id}/execute",
            json={"simulate_drift_type": "price_drift", "drift_shipping_fee": -9999},
        )
        assert bad_fee.status_code == 422


@pytest.mark.asyncio
async def test_state_errors_name_the_state_plainly():
    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        await client.post(f"/api/checkouts/{checkout_id}/execute", json={})  # now PAID
        resp = await client.post(f"/api/checkouts/{checkout_id}/approve", json={})
        assert resp.status_code == 400
        assert "TransactionState." not in resp.json()["detail"]
        assert "'PAID'" in resp.json()["detail"]
