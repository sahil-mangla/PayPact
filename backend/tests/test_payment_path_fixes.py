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


@pytest.mark.asyncio
async def test_reconcile_does_not_double_count_spend_on_a_paid_checkout():
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    spent = coordinator.get_policy(session.policy_id).spent_total
    assert spent > 0

    for _ in range(3):
        result = await coordinator.reconcile_timeout(session.checkout_id)
        assert result.state.value == "PAID"
    assert coordinator.get_policy(session.policy_id).spent_total == spent


@pytest.mark.asyncio
async def test_reconcile_refuses_checkouts_that_are_not_awaiting_reconciliation():
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    with pytest.raises(ValueError):
        await coordinator.reconcile_timeout(session.checkout_id)
    assert coordinator.get_session(session.checkout_id).state.value == "CHECKOUT_CREATED"


@pytest.mark.asyncio
async def test_reconcile_aborts_cleanly_when_no_order_was_ever_created():
    from app.api.routers import coordinator

    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
    timed_out = await coordinator.create_paypal_order_only(
        checkout_id, simulate_timeout=True
    )
    assert timed_out.state.value == "RECONCILIATION_REQUIRED"
    assert timed_out.paypal_order_id is None

    result = await coordinator.reconcile_timeout(checkout_id)
    assert result.state.value == "FAILED"
    assert coordinator.get_policy(result.policy_id).spent_total == 0


async def _paid_checkout(prompt: str = AUTO_PROMPT):
    coordinator, session = await _checkout_with_order(prompt)
    paid = await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    assert paid.state.value == "PAID"
    return coordinator, paid


def _refund(amount: float, capture_id: str):
    return {"id": "REFUND-1", "amount": {"value": f"{amount:.2f}", "currency_code": "INR"},
            "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]}


@pytest.mark.asyncio
async def test_replayed_refund_event_is_credited_once():
    coordinator, paid = await _paid_checkout()
    policy = coordinator.get_policy(paid.policy_id)
    before = policy.spent_total
    resource = _refund(100.0, paid.paypal_capture_id)

    for _ in range(3):
        await coordinator.process_webhook_event(
            "PAYMENT.CAPTURE.REFUNDED", resource, event_id="WH-EVT-1"
        )
    assert policy.spent_total == round(before - 100.0, 2)


@pytest.mark.asyncio
async def test_refunds_are_capped_at_the_amount_that_was_paid():
    coordinator, paid = await _paid_checkout()
    policy = coordinator.get_policy(paid.policy_id)
    total = paid.proposal.total_amount

    for i in range(4):
        await coordinator.process_webhook_event(
            "PAYMENT.CAPTURE.REFUNDED",
            _refund(total, paid.paypal_capture_id),
            event_id=f"WH-EVT-{i}",
        )
    assert policy.spent_total == 0.0
    assert coordinator.get_session(paid.checkout_id).state.value == "REFUNDED"


@pytest.mark.asyncio
async def test_partial_refund_keeps_the_checkout_paid():
    coordinator, paid = await _paid_checkout()
    updated = await coordinator.process_webhook_event(
        "PAYMENT.CAPTURE.REFUNDED",
        _refund(100.0, paid.paypal_capture_id),
        event_id="WH-EVT-P",
    )
    assert updated.state.value == "PAID"


@pytest.mark.asyncio
async def test_refund_for_an_unpaid_checkout_is_ignored():
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    policy = coordinator.get_policy(session.policy_id)
    await coordinator.process_webhook_event(
        "PAYMENT.CAPTURE.REFUNDED",
        {"id": session.paypal_order_id, "amount": {"value": "50.00"}},
        checkout_id=session.checkout_id,
    )
    assert coordinator.get_session(session.checkout_id).state.value == "CHECKOUT_CREATED"
    assert policy.spent_total == 0.0


@pytest.mark.asyncio
async def test_real_paypal_refund_payload_is_matched_to_its_checkout():
    coordinator, paid = await _paid_checkout()
    payload = {
        "id": "REFUND-XYZ",
        "amount": {"value": f"{paid.proposal.total_amount:.2f}", "currency_code": "INR"},
        "supplementary_data": {"related_ids": {"order_id": paid.paypal_order_id}},
    }
    updated = await coordinator.process_webhook_event(
        "PAYMENT.CAPTURE.REFUNDED", payload, event_id="WH-EVT-R"
    )
    assert updated is not None and updated.checkout_id == paid.checkout_id


@pytest.mark.asyncio
async def test_malformed_refund_amount_does_not_raise_or_change_the_budget():
    coordinator, paid = await _paid_checkout()
    policy = coordinator.get_policy(paid.policy_id)
    before = policy.spent_total
    for bad in ["abc", "-5", "nan", "inf"]:
        await coordinator.process_webhook_event(
            "PAYMENT.CAPTURE.REFUNDED",
            {"id": paid.paypal_capture_id, "amount": {"value": bad}},
            checkout_id=paid.checkout_id,
            event_id=f"WH-BAD-{bad}",
        )
    assert policy.spent_total == before
    assert coordinator.get_session(paid.checkout_id).state.value == "PAID"


@pytest.mark.asyncio
async def test_simulated_webhooks_are_closed_when_running_against_live_paypal(monkeypatch):
    from app.api.routers import coordinator

    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        await client.post(f"/api/checkouts/{checkout_id}/execute", json={})

        monkeypatch.setattr(coordinator.paypal_client, "mock_mode", False)
        monkeypatch.delenv("ENABLE_WEBHOOK_SIMULATION", raising=False)
        resp = await client.post(
            "/api/webhooks/simulate", json={"checkout_id": checkout_id}
        )
        assert resp.status_code == 403
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "PAID"

        monkeypatch.setenv("ENABLE_WEBHOOK_SIMULATION", "true")
        resp = await client.post(
            "/api/webhooks/simulate", json={"checkout_id": checkout_id}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_simulated_webhook_rejects_non_positive_amounts():
    async with _client() as client:
        checkout_id = await _new_checkout(client, AUTO_PROMPT)
        await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        for amount in (-500, 0):
            resp = await client.post(
                "/api/webhooks/simulate",
                json={"checkout_id": checkout_id, "amount": amount},
            )
            assert resp.status_code == 422


@pytest.mark.asyncio
async def test_registering_a_policy_ignores_client_supplied_spend_and_revocation():
    async with _client() as client:
        intent = (
            await client.post(
                "/api/authorizations/parse-intent", json={"prompt": AUTO_PROMPT}
            )
        ).json()
        intent.update({"spent_total": 4999.0, "is_revoked": True})
        registered = (await client.post("/api/authorizations", json=intent)).json()
        assert registered["spent_total"] == 0
        assert registered["is_revoked"] is False


@pytest.mark.asyncio
async def test_an_existing_policy_cannot_be_overwritten_through_the_api():
    async with _client() as client:
        intent = (
            await client.post(
                "/api/authorizations/parse-intent", json={"prompt": AUTO_PROMPT}
            )
        ).json()
        assert (await client.post("/api/authorizations", json=intent)).status_code == 200
        await client.post(f"/api/authorizations/{intent['policy_id']}/revoke")

        again = await client.post("/api/authorizations", json=intent)
        assert again.status_code == 409
        policy = (await client.get(f"/api/authorizations/{intent['policy_id']}")).json()
        assert policy["is_revoked"] is True
