"""Regression tests for payment-path defects found in the pre-submission review."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

APPROVAL_PROMPT = "Find a mechanical keyboard under ₹5,000, auto-buy under ₹1,000"
AUTO_PROMPT = "Find a mechanical keyboard under ₹5,000, auto-buy under ₹4,000"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _new_checkout(client: AsyncClient, policy_prompt: str) -> str:
    intent = await client.post(
        "/api/authorizations/parse-intent", json={"prompt": policy_prompt}
    )
    policy = (await client.post("/api/authorizations", json=intent.json())).json()
    proposal = await client.post(
        "/api/proposals",
        json={
            "prompt": "Keychron K2 wireless mechanical keyboard",
            "policy_id": policy["policy_id"],
        },
    )
    assert proposal.status_code == 200
    return proposal.json()["checkout_id"]


@pytest.mark.asyncio
async def test_approved_proposal_above_auto_limit_can_be_paid():
    async with _client() as client:
        checkout_id = await _new_checkout(client, APPROVAL_PROMPT)
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AWAITING_APPROVAL"

        approve = await client.post(f"/api/checkouts/{checkout_id}/approve", json={})
        assert approve.status_code == 200

        execute = await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        assert execute.status_code == 200
        session = execute.json()["session"]
        assert session["state"] == "PAID", session["failure_reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift", [{"simulate_drift_type": "price_drift"}, {"simulate_drift_type": "sku_substitution"}]
)
async def test_auto_authorized_checkout_rejects_drift(drift):
    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AUTHORIZED"

        execute = await client.post(f"/api/checkouts/{checkout_id}/execute", json=drift)
        session = execute.json()["session"]
        assert session["state"] == "POLICY_REJECTED"
        assert session["paypal_order_id"] is None


def test_fingerprint_alone_does_not_count_as_user_approval():
    from app.agent.shopper_agent import ShopperAgent
    from app.models.schemas import PolicyDecisionType
    from app.policy.engine import DeterministicPolicyEngine

    policy = ShopperAgent.parse_intent_to_policy(APPROVAL_PROMPT, user_id="u")
    proposal = ShopperAgent.generate_proposal(
        user_prompt="Keychron K2 wireless mechanical keyboard", policy=policy
    )["proposal"]
    from app.fingerprint.canonical import compute_proposal_fingerprint

    fp = compute_proposal_fingerprint(proposal)
    result = DeterministicPolicyEngine.revalidate_pre_execution(
        proposal, policy, approved_fingerprint=fp
    )
    assert result.decision == PolicyDecisionType.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_paypal_order_is_built_from_stored_proposal_not_request_data(monkeypatch):
    from app.api.routers import coordinator

    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        session = coordinator.get_session(checkout_id)

        seen = {}
        real_create = coordinator.paypal_client.create_order

        async def spy_create(proposal, request_id=None):
            seen["proposal"] = proposal
            return await real_create(proposal=proposal, request_id=request_id)

        monkeypatch.setattr(coordinator.paypal_client, "create_order", spy_create)

        # Same fingerprinted content, but a different object and a different (unsigned) proposal_id.
        forged = session.proposal.model_copy(deep=True)
        forged.proposal_id = "prop_forged"
        result = await coordinator.execute_payment(
            checkout_id, current_proposal_state=forged
        )
        assert result.state.value == "PAID", result.failure_reason

        assert seen["proposal"] is session.proposal
        assert seen["proposal"].proposal_id != "prop_forged"


async def _checkout_with_order(prompt: str):
    """Two-phase (live-sandbox style) flow: gate + create order, no capture yet."""
    from app.api.routers import coordinator

    async with _client() as client:
        checkout_id = await _new_checkout(client, prompt)
        if prompt == APPROVAL_PROMPT:
            await client.post(f"/api/checkouts/{checkout_id}/approve", json={})
    session = await coordinator.create_paypal_order_only(checkout_id)
    assert session.state.value == "CHECKOUT_CREATED"
    return coordinator, session


@pytest.mark.asyncio
async def test_capture_is_refused_for_a_checkout_that_never_created_an_order():
    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        # Another checkout's real order id must not be capturable through this one.
        _, other = await _checkout_with_order(AUTO_PROMPT)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/capture",
            json={"paypal_order_id": other.paypal_order_id},
        )
        assert resp.status_code == 400
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AUTHORIZED"


@pytest.mark.asyncio
async def test_capture_is_refused_for_a_rejected_checkout():
    from app.api.routers import coordinator

    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        await client.post(
            f"/api/checkouts/{checkout_id}/execute",
            json={"simulate_drift_type": "price_drift"},
        )
        _, other = await _checkout_with_order(AUTO_PROMPT)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/capture",
            json={"paypal_order_id": other.paypal_order_id},
        )
        assert resp.status_code == 400
        assert coordinator.get_session(checkout_id).state.value == "POLICY_REJECTED"


@pytest.mark.asyncio
async def test_capture_reruns_the_gate_so_a_revoked_policy_cannot_be_paid():
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    coordinator.revoke_policy(session.policy_id)

    result = await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    assert result.state.value == "POLICY_REJECTED"
    assert result.paypal_capture_id is None
    assert coordinator.get_policy(session.policy_id).spent_total == 0


@pytest.mark.asyncio
async def test_capture_rejects_malformed_order_ids():
    async with _client() as client:
        _, session = await _checkout_with_order(AUTO_PROMPT)
        for bad in ["../v1/payments", "a/b", "x" * 80, "ord id"]:
            resp = await client.post(
                f"/api/checkouts/{session.checkout_id}/capture",
                json={"paypal_order_id": bad},
            )
            assert resp.status_code == 422, bad


@pytest.mark.asyncio
async def test_capture_after_payment_is_idempotent():
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    first = await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    assert first.state.value == "PAID"
    spent = coordinator.get_policy(session.policy_id).spent_total
    second = await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    assert second.state.value == "PAID"
    assert coordinator.get_policy(session.policy_id).spent_total == spent
