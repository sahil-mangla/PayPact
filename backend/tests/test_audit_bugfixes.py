import pytest
from app.agent.shopper_agent import ShopperAgent
from app.models.schemas import LineItem, PurchaseProposal, TransactionState
from app.policy.engine import DeterministicPolicyEngine, PolicyDecisionType
from app.payments.paypal_client import PayPalClient
from app.state.machine import TransactionCoordinator


@pytest.mark.asyncio
async def test_travel_agent_intent_and_proposal():
    prompt = "Book economy flights to Bangalore under ₹5,000."
    policy = ShopperAgent.parse_intent_to_policy(prompt)

    # 1. Category must be travel
    assert policy.product_category == "travel"

    # 2. Travel agent quota must be allocated up to max_total (not restricted to 50%)
    assert policy.agent_quotas["agent_travel"].allocated_budget == 5000.00
    assert "IndiGo Corporate" in policy.allowed_merchants

    # 3. Generate proposal targeting travel agent
    res = ShopperAgent.generate_proposal(prompt, policy, agent_id="agent_travel")
    proposal: PurchaseProposal = res["proposal"]

    # Must select the IndiGo flight ticket, not a keyboard!
    assert proposal.items[0].sku == "TR-FLIGHT-BLR"
    assert proposal.merchant == "IndiGo Corporate"
    assert proposal.total_amount == 4299.00

    # 4. Deterministic policy evaluation must pass merchant and quota checks
    eval_res = DeterministicPolicyEngine.evaluate(proposal, policy)
    assert eval_res.decision in (PolicyDecisionType.ALLOW, PolicyDecisionType.REQUIRE_APPROVAL)
    for check in eval_res.checks:
        if check.check_name in ("merchant_check", "agent_quota_check", "maximum_budget_check"):
            assert check.passed is True


@pytest.mark.asyncio
async def test_supplies_agent_intent_and_proposal():
    prompt = "Order custom brass keyboard desk mat under ₹2,000."
    policy = ShopperAgent.parse_intent_to_policy(prompt)

    assert policy.product_category == "office supplies"
    assert policy.agent_quotas["agent_supplies"].allocated_budget == 2000.00

    res = ShopperAgent.generate_proposal(prompt, policy, agent_id="agent_supplies")
    proposal: PurchaseProposal = res["proposal"]

    assert proposal.items[0].sku == "SP-DESK-MAT-BRASS"
    assert proposal.total_amount == 1899.00


@pytest.mark.asyncio
async def test_reconcile_timeout_spend_accounting():
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = ShopperAgent.parse_intent_to_policy("Test keyboard under 5000")
    coord.register_policy(policy)

    res = ShopperAgent.generate_proposal("Test keyboard under 5000", policy, preferred_sku="KB-K2-V2-RGB")
    session = coord.create_proposal_session(res["proposal"], policy)

    # Simulate ambiguous timeout during execute
    session = await coord.execute_payment(session.checkout_id, simulate_timeout=True)
    assert session.state == TransactionState.RECONCILIATION_REQUIRED
    assert policy.spent_total == 0.0

    # Simulate that PayPal actually captured the order before the network dropped
    coord.paypal_client._mock_orders_store[session.paypal_order_id]["status"] = "COMPLETED"
    coord.paypal_client._mock_orders_store[session.paypal_order_id]["capture_id"] = "MOCK-CAP-RECON-01"

    # Reconcile timeout
    reconciled = await coord.reconcile_timeout(session.checkout_id)
    assert reconciled.state == TransactionState.PAID

    # Spend MUST be recorded
    assert policy.spent_total == res["proposal"].total_amount
    assert policy.agent_quotas["agent_hardware"].spent_budget == res["proposal"].total_amount


@pytest.mark.asyncio
async def test_live_sandbox_timeout_simulation():
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = ShopperAgent.parse_intent_to_policy("Test keyboard under 5000")
    coord.register_policy(policy)

    res = ShopperAgent.generate_proposal("Test keyboard under 5000", policy, preferred_sku="KB-K2-V2-RGB")
    session = coord.create_proposal_session(res["proposal"], policy)

    # create_paypal_order_only with simulate_timeout=True
    updated = await coord.create_paypal_order_only(session.checkout_id, simulate_timeout=True)
    assert updated.state == TransactionState.RECONCILIATION_REQUIRED
    assert "timeout" in (updated.failure_reason or "").lower()


@pytest.mark.asyncio
async def test_webhook_null_amount_resilience():
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = ShopperAgent.parse_intent_to_policy("Test keyboard under 5000")
    coord.register_policy(policy)

    res = ShopperAgent.generate_proposal("Test keyboard under 5000", policy, preferred_sku="KB-K2-V2-RGB")
    session = coord.create_proposal_session(res["proposal"], policy)
    session = await coord.execute_payment(session.checkout_id)
    assert session.state == TransactionState.PAID

    # Webhook with amount=None must not raise AttributeError
    resource_with_none_amount = {
        "id": session.paypal_capture_id,
        "amount": None,
    }
    updated = await coord.process_webhook_event(
        event_type="PAYMENT.CAPTURE.REFUNDED",
        resource=resource_with_none_amount,
        checkout_id=session.checkout_id,
    )
    assert updated is not None
    assert updated.state == TransactionState.REFUNDED
