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


@pytest.mark.asyncio
async def test_execute_after_the_popup_was_closed_returns_the_same_order(monkeypatch):
    coordinator, session = await _checkout_with_order(AUTO_PROMPT)
    first_order = session.paypal_order_id

    calls = []
    real_create = coordinator.paypal_client.create_order

    async def counting_create(proposal, request_id=None):
        calls.append(request_id)
        return await real_create(proposal=proposal, request_id=request_id)

    monkeypatch.setattr(coordinator.paypal_client, "create_order", counting_create)

    again = await coordinator.create_paypal_order_only(session.checkout_id)
    assert again.state.value == "CHECKOUT_CREATED"
    assert again.paypal_order_id == first_order
    assert calls == []


@pytest.mark.asyncio
async def test_pending_checkouts_count_against_the_budget():
    """Two checkouts that each fit the budget must not both be allowed to start paying."""
    from app.api.routers import coordinator

    async with _client() as client:
        intent = (
            await client.post(
                "/api/authorizations/parse-intent", json={"prompt": AUTO_PROMPT}
            )
        ).json()
        policy = (await client.post("/api/authorizations", json=intent)).json()
        ids = []
        for _ in range(2):
            proposal = await client.post(
                "/api/proposals",
                json={
                    "prompt": "Keychron K2 wireless mechanical keyboard",
                    "policy_id": policy["policy_id"],
                },
            )
            ids.append(proposal.json()["checkout_id"])

    first = await coordinator.create_paypal_order_only(ids[0])
    second = await coordinator.create_paypal_order_only(ids[1])

    assert first.state.value == "CHECKOUT_CREATED"
    assert first.proposal.total_amount * 2 > policy["maximum_total"]
    assert second.state.value == "POLICY_REJECTED"
    assert "pending" in second.failure_reason.lower()
    assert second.paypal_order_id is None


def _proposal(currency="INR", unit_price=3899.0, shipping=0.0, tax=0.0):
    from app.models.schemas import LineItem, PurchaseProposal

    return PurchaseProposal(
        proposal_id="prop_t",
        policy_id="pol_t",
        policy_version=1,
        merchant="Keychron",
        items=[LineItem(sku="KB", name="Keyboard", quantity=1, unit_price=unit_price)],
        item_subtotal=unit_price,
        shipping_fee=shipping,
        tax_fee=tax,
        total_amount=round(unit_price + shipping + tax, 2),
        currency=currency,
    )


def test_unsupported_currencies_are_refused_instead_of_charged_one_to_one():
    from app.payments.paypal_client import PayPalClient

    client = PayPalClient(mock_mode=False, client_id="x", client_secret="y")
    with pytest.raises(ValueError, match="BRL"):
        client.charge_for(_proposal(currency="BRL"))


def test_zero_decimal_currency_is_sent_without_fractional_digits():
    from app.payments.paypal_client import PayPalClient

    client = PayPalClient(mock_mode=False, client_id="x", client_secret="y")
    charge = client.charge_for(_proposal(currency="JPY", unit_price=1500.0))
    assert charge.currency == "JPY"
    assert charge.total_value == "1500"
    assert charge.items[0]["unit_amount"]["value"] == "1500"


def test_inr_is_converted_to_usd_for_the_sandbox():
    from app.payments.paypal_client import PayPalClient

    client = PayPalClient(mock_mode=False, client_id="x", client_secret="y")
    charge = client.charge_for(_proposal(currency="INR", unit_price=8300.0))
    assert charge.currency == "USD"
    assert charge.total_value == "100.00"


@pytest.mark.asyncio
async def test_capture_that_does_not_match_the_approved_amount_is_not_marked_paid(monkeypatch):
    from app.payments.paypal_client import PayPalOrderResponse

    coordinator, session = await _checkout_with_order(AUTO_PROMPT)

    async def wrong_amount_capture(order_id, request_id=None):
        return PayPalOrderResponse(
            order_id=order_id,
            status="COMPLETED",
            intent="CAPTURE",
            capture_id="CAP-X",
            total_amount=session.proposal.total_amount + 500,
            currency=session.proposal.currency,
            is_mock=True,
        )

    monkeypatch.setattr(coordinator.paypal_client, "capture_order", wrong_amount_capture)
    result = await coordinator.capture_approved_order(
        session.checkout_id, session.paypal_order_id
    )
    assert result.state.value == "FAILED"
    assert "does not match" in result.failure_reason
    assert coordinator.get_policy(session.policy_id).spent_total == 0
    events = coordinator.audit_ledger.get_events(checkout_id=session.checkout_id)
    assert any(e.event_type == "PAYMENT_AMOUNT_MISMATCH" for e in events)


def _live_client_with_transport(monkeypatch, handler):
    """A non-mock PayPalClient whose HTTP calls are answered by `handler`."""
    import httpx

    from app.payments import paypal_client as module

    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    client = module.PayPalClient(
        client_id="id", client_secret="secret", base_url="https://sandbox.paypal.test", mock_mode=False
    )
    client._access_token = "tok"
    client._token_expires_at = 10**12
    return client


@pytest.mark.asyncio
async def test_live_create_order_sends_idempotency_key_and_exact_totals(monkeypatch):
    import httpx
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["request_id"] = request.headers.get("PayPal-Request-Id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "ORD123", "status": "CREATED", "links": []})

    client = _live_client_with_transport(monkeypatch, handler)
    proposal = _proposal(currency="USD", unit_price=40.0, shipping=5.5, tax=2.25)
    order = await client.create_order(proposal, request_id="req-1")

    assert order.order_id == "ORD123"
    assert seen["url"] == "https://sandbox.paypal.test/v2/checkout/orders"
    assert seen["request_id"] == "req-1"
    unit = seen["body"]["purchase_units"][0]
    assert unit["amount"]["value"] == "47.75"
    assert unit["amount"]["breakdown"]["shipping"]["value"] == "5.50"


@pytest.mark.asyncio
async def test_live_capture_reads_the_amount_from_the_capture_not_the_purchase_unit(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/checkout/orders/ORD123/capture"
        return httpx.Response(
            201,
            json={
                "id": "ORD123",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {"id": "CAP9", "amount": {"currency_code": "USD", "value": "47.75"}}
                            ]
                        }
                    }
                ],
            },
        )

    client = _live_client_with_transport(monkeypatch, handler)
    resp = await client.capture_order("ORD123", request_id="req-1_cap")
    assert resp.capture_id == "CAP9"
    assert resp.total_amount == 47.75
    assert resp.currency == "USD"


@pytest.mark.asyncio
async def test_live_capture_without_a_reported_amount_is_not_treated_as_a_mismatch(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "ORD123", "status": "COMPLETED"})

    client = _live_client_with_transport(monkeypatch, handler)
    resp = await client.capture_order("ORD123")
    assert resp.amount_reported is False


def _llm_returns(monkeypatch, data):
    monkeypatch.setattr(
        "app.agent.gemini_client.GeminiClient.parse_intent", classmethod(lambda cls, p: data)
    )


def test_an_llm_budget_the_user_never_typed_is_ignored(monkeypatch):
    from app.agent.shopper_agent import ShopperAgent

    _llm_returns(
        monkeypatch,
        {"category": "keyboard", "max_budget": 900000, "auto_buy_limit": 800000, "currency": "INR"},
    )
    policy = ShopperAgent.parse_intent_to_policy(
        "Find a mechanical keyboard under ₹5,000, auto-buy under ₹4,000"
    )
    assert policy.maximum_total == 5000.0
    assert policy.automatic_purchase_limit == 4000.0


def test_an_llm_budget_that_matches_the_prompt_is_kept(monkeypatch):
    from app.agent.shopper_agent import ShopperAgent

    _llm_returns(
        monkeypatch,
        {"category": "keyboard", "max_budget": 7500, "auto_buy_limit": 6000, "currency": "INR"},
    )
    policy = ShopperAgent.parse_intent_to_policy("keyboard, 7500 max, auto 6,000")
    assert policy.maximum_total == 7500.0
    assert policy.automatic_purchase_limit == 6000.0


def test_k_suffix_amounts_count_as_typed_by_the_user(monkeypatch):
    from app.agent.shopper_agent import ShopperAgent

    _llm_returns(monkeypatch, {"category": "keyboard", "max_budget": 5000, "currency": "INR"})
    policy = ShopperAgent.parse_intent_to_policy("keyboard under 5k")
    assert policy.maximum_total == 5000.0


@pytest.mark.asyncio
async def test_health_does_not_expose_credentials_or_internal_urls():
    async with _client() as client:
        body = (await client.get("/api/health")).json()
        status = (await client.get("/api/agent/model-status")).json()
    text = str(body) + str(status)
    assert "paypal_client_id" not in body
    assert "base_url" not in text
    assert "models_list" not in text
    assert "paypal_mode" in body


@pytest.mark.asyncio
async def test_health_probes_models_once_per_cache_window(monkeypatch):
    from app.agent.gemini_client import GeminiClient
    from app.agent.ollama_client import OllamaClient

    calls = {"ollama": 0, "gemini": 0}

    def ollama(cls):
        calls["ollama"] += 1
        return {"available": False, "model": "m"}

    def gemini(cls):
        calls["gemini"] += 1
        return {"available": False, "model": "g"}

    monkeypatch.setattr(OllamaClient, "check_health", classmethod(ollama))
    monkeypatch.setattr(GeminiClient, "check_health", classmethod(gemini))
    async with _client() as client:
        for _ in range(5):
            assert (await client.get("/api/health")).status_code == 200
    assert calls == {"ollama": 1, "gemini": 1}


@pytest.mark.asyncio
async def test_slow_llm_calls_do_not_block_other_requests(monkeypatch):
    import asyncio
    import time

    from app.agent.shopper_agent import ShopperAgent

    real = ShopperAgent.parse_intent_to_policy

    def slow(cls, user_prompt, user_id="usr_demo"):
        time.sleep(0.4)
        return real(user_prompt, user_id=user_id)

    monkeypatch.setattr(ShopperAgent, "parse_intent_to_policy", classmethod(slow))
    async with _client() as client:
        started = time.monotonic()
        slow_call = asyncio.create_task(
            client.post("/api/authorizations/parse-intent", json={"prompt": AUTO_PROMPT})
        )
        await asyncio.sleep(0.05)
        await client.get("/api/catalogue")
        fast_elapsed = time.monotonic() - started
        assert (await slow_call).status_code == 200
    assert fast_elapsed < 0.3


@pytest.mark.asyncio
async def test_oversized_prompts_are_rejected():
    async with _client() as client:
        resp = await client.post(
            "/api/authorizations/parse-intent", json={"prompt": "x" * 2_000_000}
        )
        assert resp.status_code == 422
        resp = await client.post(
            "/api/proposals", json={"prompt": "y" * 501, "policy_id": "pol_x"}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_llm_endpoints_are_rate_limited_per_client(monkeypatch):
    from app.api.ratelimit import llm_limiter

    monkeypatch.setattr(llm_limiter, "_limit", lambda: 3)
    async with _client() as client:
        codes = [
            (
                await client.post(
                    "/api/authorizations/parse-intent", json={"prompt": AUTO_PROMPT}
                )
            ).status_code
            for _ in range(5)
        ]
        assert codes == [200, 200, 200, 429, 429]
        # Cheap read-only endpoints are not throttled.
        assert (await client.get("/api/catalogue")).status_code == 200


def test_gemini_daily_call_cap_falls_back_instead_of_calling(monkeypatch):
    import httpx

    from app.agent import gemini_client
    from app.agent.gemini_client import GeminiClient

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"candidates": []})

    real_client = httpx.Client
    monkeypatch.setattr(
        gemini_client.httpx,
        "Client",
        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "2")
    monkeypatch.setattr(GeminiClient, "get_api_key", classmethod(lambda cls: "k"))
    GeminiClient.reset_daily_budget()

    for _ in range(4):
        GeminiClient.parse_intent("keyboard under 5000")
    assert len(sent) == 2


def test_client_refuses_to_run_against_live_paypal_by_accident(monkeypatch):
    from app.payments.paypal_client import PayPalClient

    monkeypatch.delenv("ALLOW_LIVE_PAYPAL", raising=False)
    with pytest.raises(ValueError, match="sandbox"):
        PayPalClient(
            client_id="a", client_secret="b", base_url="https://api-m.paypal.com", mock_mode=False
        )
    # Sandbox and mock are fine, and live needs an explicit opt-in.
    PayPalClient(client_id="a", client_secret="b", base_url="https://api-m.sandbox.paypal.com")
    PayPalClient(base_url="https://api-m.paypal.com", mock_mode=True)
    monkeypatch.setenv("ALLOW_LIVE_PAYPAL", "true")
    PayPalClient(
        client_id="a", client_secret="b", base_url="https://api-m.paypal.com", mock_mode=False
    )
