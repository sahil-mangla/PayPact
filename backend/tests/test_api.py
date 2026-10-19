import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_end_to_end_api_lifecycle():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Parse intent
        intent_resp = await client.post(
            "/api/authorizations/parse-intent",
            json={
                "prompt": "Find a mechanical keyboard under ₹5,000, auto-buy under ₹4,000"
            },
        )
        assert intent_resp.status_code == 200
        policy_data = intent_resp.json()
        assert policy_data["maximum_total"] == 5000.00
        assert policy_data["automatic_purchase_limit"] == 4000.00

        # 2. Register policy
        reg_resp = await client.post("/api/authorizations", json=policy_data)
        assert reg_resp.status_code == 200
        policy_id = reg_resp.json()["policy_id"]

        # 3. Create proposal
        prop_resp = await client.post(
            "/api/proposals",
            json={
                "prompt": "Keychron K2 wireless mechanical keyboard",
                "policy_id": policy_id,
            },
        )
        assert prop_resp.status_code == 200
        proposal_res = prop_resp.json()
        checkout_id = proposal_res["checkout_id"]
        assert proposal_res["state"] == "AUTHORIZED"

        # 4. Execute checkout (nominal)
        exec_resp = await client.post(
            f"/api/checkouts/{checkout_id}/execute",
            json={},
        )
        assert exec_resp.status_code == 200
        exec_res = exec_resp.json()
        # Response is now wrapped: {session: {...}, paypal_mode: "mock"|"live_sandbox", ...}
        session_data = exec_res.get(
            "session", exec_res
        )  # handle both old and new format
        assert session_data["state"] == "PAID"
        assert session_data["paypal_order_id"] is not None

        # 5. Check audit events
        audit_resp = await client.get("/api/audit/events")
        assert audit_resp.status_code == 200
        audit_data = audit_resp.json()
        assert audit_data["ledger_integrity_valid"] is True
        assert audit_data["event_count"] >= 3


@pytest.mark.asyncio
async def test_api_lab_scenarios_and_benchmark():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # List scenarios
        sc_resp = await client.get("/api/lab/scenarios")
        assert sc_resp.status_code == 200
        scenarios = sc_resp.json()
        assert len(scenarios) == 7

        # Run single scenario
        run_resp = await client.post(
            "/api/lab/run",
            json={"scenario_id": "SC-B", "system_type": "PROPOSED_APIL"},
        )
        assert run_resp.status_code == 200
        single_run = run_resp.json()["single_run"]
        assert single_run["scenario_id"] == "SC-B"
        assert single_run["drift_detected"] is True
        assert single_run["protection_successful"] is True
