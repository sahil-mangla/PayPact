"""Tests for Multi-Agent Swarm Hierarchy, Signed Audit Receipts, and Webhooks."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto.receipts import generate_signed_receipt, verify_signed_receipt
from app.main import app
from app.models.schemas import (
    AgentQuota,
    AuthorizationPolicy,
    LineItem,
    PolicyDecisionType,
    PurchaseProposal,
    TransactionState,
)
from app.policy.engine import DeterministicPolicyEngine
from app.state.machine import TransactionCoordinator


@pytest.fixture
def swarm_policy():
    quotas = {
        "agent_hardware": AgentQuota(
            agent_id="agent_hardware",
            agent_name="Hardware Agent",
            role="Hardware",
            allocated_budget=2000.0,
            spent_budget=0.0,
        ),
        "agent_travel": AgentQuota(
            agent_id="agent_travel",
            agent_name="Travel Agent",
            role="Travel",
            allocated_budget=1000.0,
            spent_budget=0.0,
        ),
        "agent_inactive": AgentQuota(
            agent_id="agent_inactive",
            agent_name="Inactive Agent",
            role="Experimental",
            allocated_budget=500.0,
            spent_budget=0.0,
            is_active=False,
        ),
    }
    return AuthorizationPolicy(
        policy_id="pol_swarm_test",
        version=1,
        user_id="usr_admin",
        maximum_total=2500.0,  # Note master is 2500, sum of quotas is 3500 (over-allocated tree)
        spent_total=0.0,
        automatic_purchase_limit=2000.0,
        allowed_currencies=["USD"],
        agent_quotas=quotas,
    )


def test_swarm_agent_quota_exceeded(swarm_policy):
    """Proposal exceeding individual agent quota is rejected even if master has budget."""
    proposal = PurchaseProposal(
        proposal_id="prop_sw_01",
        policy_id="pol_swarm_test",
        policy_version=1,
        agent_id="agent_travel",  # Travel quota is 1000
        merchant="Airline Inc",
        items=[
            LineItem(
                sku="FLIGHT-01", name="Flight Ticket", quantity=1, unit_price=1200.0
            )
        ],
        item_subtotal=1200.0,
        shipping_fee=0.0,
        tax_fee=0.0,
        total_amount=1200.0,  # 1200 > 1000 (exceeds agent quota, but <= master 2500)
        currency="USD",
    )
    result = DeterministicPolicyEngine.evaluate(proposal, swarm_policy)
    assert result.decision == PolicyDecisionType.REJECT
    assert "Exceeds agent 'Travel Agent' quota" in result.primary_reason


def test_swarm_deactivated_agent_rejected(swarm_policy):
    """Deactivated agent persona is blocked immediately."""
    proposal = PurchaseProposal(
        proposal_id="prop_sw_02",
        policy_id="pol_swarm_test",
        policy_version=1,
        agent_id="agent_inactive",
        merchant="Tech Store",
        items=[LineItem(sku="ITEM-01", name="Gadget", quantity=1, unit_price=100.0)],
        item_subtotal=100.0,
        total_amount=100.0,
        currency="USD",
    )
    result = DeterministicPolicyEngine.evaluate(proposal, swarm_policy)
    assert result.decision == PolicyDecisionType.REJECT
    assert "is deactivated" in result.primary_reason


def test_swarm_master_budget_ceiling_enforced(swarm_policy):
    """Cumulative master spend caps total across swarm even if individual agent has quota remaining."""
    # Simulate prior spend of 2200 on master policy (out of 2500 max)
    swarm_policy.spent_total = 2200.0
    # Hardware agent has quota of 2000 and spent 0, but master only has 300 remaining!
    proposal = PurchaseProposal(
        proposal_id="prop_sw_03",
        policy_id="pol_swarm_test",
        policy_version=1,
        agent_id="agent_hardware",
        merchant="Keychron India",
        items=[LineItem(sku="KB-01", name="Keyboard", quantity=1, unit_price=500.0)],
        item_subtotal=500.0,
        total_amount=500.0,  # 500 > 300 remaining on master
        currency="USD",
    )
    result = DeterministicPolicyEngine.evaluate(proposal, swarm_policy)
    assert result.decision == PolicyDecisionType.REJECT
    assert "Exceeds remaining master budget" in result.primary_reason


def test_signed_audit_receipt_generation_and_tamper_detection():
    """Verify cryptographic receipt generation and detect malicious tampering."""
    receipt = generate_signed_receipt(
        checkout_id="chk_receipt_001",
        decision="ALLOW",
        status="PAID",
        policy_id="pol_test",
        policy_version=1,
        proposal_fingerprint="sha256_mock_fp_1234567890abcdef",
        total_amount=49.99,
        currency="USD",
        merchant="Keychron India",
        items_count=1,
        agent_id="agent_hardware",
        paypal_order_id="MOCK-ORD-1234",
        paypal_capture_id="MOCK-CAP-5678",
    )

    # 1. Nominal receipt must verify as True
    assert verify_signed_receipt(receipt) is True

    # 2. Tampered amount must fail verification
    tampered_amount = receipt.model_copy(update={"total_amount": 999.99})
    assert verify_signed_receipt(tampered_amount) is False

    # 3. Tampered fingerprint must fail verification
    tampered_fp = receipt.model_copy(
        update={"proposal_fingerprint": "altered_fingerprint_hash"}
    )
    assert verify_signed_receipt(tampered_fp) is False

    # 4. Tampered signature must fail verification
    tampered_sig = receipt.model_copy(update={"signature": "deadbeef" * 8})
    assert verify_signed_receipt(tampered_sig) is False


@pytest.mark.asyncio
async def test_webhook_refund_lifecycle_and_spend_credit():
    """Verify asynchronous webhook refund restores spent budget to agent and master policy."""
    coord = TransactionCoordinator()
    coord.paypal_client.mock_mode = True

    policy = AuthorizationPolicy(
        policy_id="pol_wb_test",
        version=1,
        user_id="usr_test",
        maximum_total=1000.0,
        spent_total=0.0,
        automatic_purchase_limit=800.0,
        allowed_currencies=["USD"],
        agent_quotas={
            "agent_hardware": AgentQuota(
                agent_id="agent_hardware",
                agent_name="Hardware Agent",
                role="Hardware",
                allocated_budget=800.0,
                spent_budget=0.0,
            )
        },
    )
    coord.register_policy(policy)

    proposal = PurchaseProposal(
        proposal_id="prop_wb_01",
        policy_id=policy.policy_id,
        policy_version=1,
        agent_id="agent_hardware",
        merchant="Keychron India",
        items=[LineItem(sku="KB-01", name="Keyboard", quantity=1, unit_price=200.0)],
        item_subtotal=200.0,
        total_amount=200.0,
        currency="USD",
    )
    session = coord.create_proposal_session(proposal, policy)

    # Execute payment
    paid_session = await coord.execute_payment(session.checkout_id)
    assert paid_session.state == TransactionState.PAID
    assert policy.spent_total == 200.0
    assert policy.agent_quotas["agent_hardware"].spent_budget == 200.0

    # Process simulated refund webhook
    refund_resource = {
        "id": paid_session.paypal_capture_id,
        "amount": {"value": "200.00", "currency_code": "USD"},
    }
    refunded_session = await coord.process_webhook_event(
        event_type="PAYMENT.CAPTURE.REFUNDED",
        resource=refund_resource,
        checkout_id=session.checkout_id,
        summary="Buyer returned item, refund issued",
    )
    assert refunded_session is not None
    assert refunded_session.state == TransactionState.REFUNDED

    # Spent totals must be credited back
    assert policy.spent_total == 0.0
    assert policy.agent_quotas["agent_hardware"].spent_budget == 0.0

    # Verify audit ledger recorded refund event
    events = coord.audit_ledger.get_events(checkout_id=session.checkout_id)
    refund_events = [e for e in events if e.event_type == "PAYMENT_REFUNDED"]
    assert len(refund_events) == 1


@pytest.mark.asyncio
async def test_api_receipt_and_simulate_webhook_endpoints():
    """Verify REST API endpoints for receipt generation, webhook simulation, and swarm personas."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Swarm personas endpoint
        personas_resp = await client.get("/api/swarm/personas")
        assert personas_resp.status_code == 200
        personas = personas_resp.json()
        assert len(personas) == 3
        assert personas[0]["agent_id"] == "agent_hardware"

        # 2. Parse intent and create proposal with agent_hardware
        intent_resp = await client.post(
            "/api/authorizations/parse-intent",
            json={"prompt": "Wireless keyboard budget ₹5000 auto ₹4000"},
        )
        policy_data = intent_resp.json()
        reg_resp = await client.post("/api/authorizations", json=policy_data)
        policy_id = reg_resp.json()["policy_id"]

        prop_resp = await client.post(
            "/api/proposals",
            json={
                "prompt": "Keychron keyboard",
                "policy_id": policy_id,
                "agent_id": "agent_hardware",
            },
        )
        checkout_id = prop_resp.json()["checkout_id"]

        # Approve (the proposal is above the auto limit), then execute checkout
        await client.post(f"/api/checkouts/{checkout_id}/approve", json={})
        paid = await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        assert paid.json()["session"]["state"] == "PAID"

        # 3. Fetch signed receipt
        receipt_resp = await client.get(f"/api/checkouts/{checkout_id}/receipt")
        assert receipt_resp.status_code == 200
        receipt = receipt_resp.json()
        assert receipt["checkout_id"] == checkout_id
        assert receipt["signature_algorithm"] == "HMAC-SHA256"
        assert len(receipt["signature"]) == 64

        # 4. Simulate refund webhook via API
        sim_resp = await client.post(
            "/api/webhooks/simulate",
            json={
                "checkout_id": checkout_id,
                "event_type": "PAYMENT.CAPTURE.REFUNDED",
                "reason": "Test refund via API",
            },
        )
        assert sim_resp.status_code == 200
        assert sim_resp.json()["session"]["state"] == "REFUNDED"

        # 5. Verify signed receipt via verification endpoint
        verify_resp = await client.post("/api/receipt/verify", json=receipt)
        assert verify_resp.status_code == 200
        assert verify_resp.json()["valid"] is True

        # Tampered verification must be rejected
        tampered_receipt = dict(receipt)
        tampered_receipt["total_amount"] = 99999.00
        tamper_resp = await client.post("/api/receipt/verify", json=tampered_receipt)
        assert tamper_resp.status_code == 200
        assert tamper_resp.json()["valid"] is False

        # 6. Sample receipt endpoint produces valid verifiable receipt
        sample_resp = await client.get("/api/receipt/sample")
        assert sample_resp.status_code == 200
        sample_receipt = sample_resp.json()
        assert sample_receipt["signature_algorithm"] == "HMAC-SHA256"
        sample_verify = await client.post("/api/receipt/verify", json=sample_receipt)
        assert sample_verify.status_code == 200
        assert sample_verify.json()["valid"] is True
