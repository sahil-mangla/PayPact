import asyncio
import copy
from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from app.audit.ledger import AuditLedger
from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    AuthorizationPolicy,
    LineItem,
    PolicyDecisionType,
    PurchaseProposal,
    TransactionState,
)
from app.payments.paypal_client import PayPalClient
from app.policy.engine import DeterministicPolicyEngine
from app.state.machine import TransactionCoordinator


# =====================================================================
# 1. Arithmetic, Extreme Numbers & Floating Point Edge Cases
# =====================================================================

def test_nan_rejected_in_unit_price():
    with pytest.raises(ValidationError):
        LineItem(sku="SKU-1", name="Item", quantity=1, unit_price=float("nan"))


def test_infinite_number_rejected_in_budget():
    with pytest.raises(ValidationError):
        AuthorizationPolicy(
            policy_id="pol_inf",
            version=1,
            user_id="usr_01",
            maximum_total=float("inf"),
            automatic_purchase_limit=4000.00,
        )


def test_negative_unit_price_rejected():
    with pytest.raises(ValidationError):
        LineItem(sku="SKU-1", name="Item", quantity=1, unit_price=-50.00)


def test_zero_quantity_rejected():
    with pytest.raises(ValidationError):
        LineItem(sku="SKU-1", name="Item", quantity=0, unit_price=10.00)


def test_negative_shipping_fee_rejected():
    item = LineItem(sku="SKU-1", name="Item", quantity=1, unit_price=10.00)
    with pytest.raises(ValidationError):
        PurchaseProposal(
            proposal_id="p1",
            policy_id="pol1",
            policy_version=1,
            merchant="Store",
            items=[item],
            item_subtotal=10.00,
            shipping_fee=-5.00,
            tax_fee=0.00,
            total_amount=5.00,
            currency="USD",
        )


def test_sub_cent_floating_point_rounding_arithmetic():
    # 0.1 + 0.2 floating point anomaly
    item1 = LineItem(sku="SKU-A", name="A", quantity=1, unit_price=0.10)
    item2 = LineItem(sku="SKU-B", name="B", quantity=1, unit_price=0.20)
    subtotal = round(item1.unit_price + item2.unit_price, 2)
    assert subtotal == 0.30

    proposal = PurchaseProposal(
        proposal_id="p1",
        policy_id="pol1",
        policy_version=1,
        merchant="Store",
        items=[item1, item2],
        item_subtotal=0.30,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=0.30,
        currency="USD",
    )
    policy = AuthorizationPolicy(
        policy_id="pol1",
        version=1,
        user_id="usr",
        maximum_total=100.0,
        automatic_purchase_limit=50.0,
        allowed_currencies=["USD"],
    )
    res = DeterministicPolicyEngine.evaluate(proposal, policy)
    assert res.decision == PolicyDecisionType.ALLOW


def test_huge_currency_amount_precision_safety():
    # 999 million
    item = LineItem(sku="LUXURY-01", name="Luxury Jet", quantity=1, unit_price=999999999.99)
    assert item.unit_price == 999999999.99


# =====================================================================
# 2. String, Case, and Injection Sanitization
# =====================================================================

def test_non_alphabetic_currency_injection_rejected():
    item = LineItem(sku="SKU-1", name="Item", quantity=1, unit_price=10.00)
    with pytest.raises(ValidationError):
        PurchaseProposal(
            proposal_id="p1",
            policy_id="pol1",
            policy_version=1,
            merchant="Store",
            items=[item],
            item_subtotal=10.00,
            shipping_fee=0.00,
            tax_fee=0.00,
            total_amount=10.00,
            currency="USD<script>",
        )


def test_merchant_case_and_whitespace_insensitivity():
    item = LineItem(sku="SKU-1", name="Item", quantity=1, unit_price=100.00)
    proposal = PurchaseProposal(
        proposal_id="p1",
        policy_id="pol1",
        policy_version=1,
        merchant="  Keychron India  ",  # Trailing and leading whitespace, mixed case
        items=[item],
        item_subtotal=100.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=100.00,
        currency="INR",
    )
    policy = AuthorizationPolicy(
        policy_id="pol1",
        version=1,
        user_id="usr",
        maximum_total=1000.0,
        automatic_purchase_limit=500.0,
        allowed_currencies=["INR"],
        allowed_merchants=["KEYCHRON INDIA"],  # Uppercase in policy
    )
    res = DeterministicPolicyEngine.evaluate(proposal, policy)
    assert res.decision == PolicyDecisionType.ALLOW


def test_identical_sku_multi_item_canonical_ordering():
    # Multiple items with same SKU but different quantities/prices
    item1 = LineItem(sku="SAME-SKU", name="Variant A", quantity=1, unit_price=50.00)
    item2 = LineItem(sku="SAME-SKU", name="Variant B", quantity=2, unit_price=25.00)

    p1 = PurchaseProposal(
        proposal_id="p1",
        policy_id="pol1",
        policy_version=1,
        merchant="Store",
        items=[item1, item2],
        item_subtotal=100.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=100.00,
        currency="USD",
    )
    p2 = PurchaseProposal(
        proposal_id="p2",
        policy_id="pol1",
        policy_version=1,
        merchant="Store",
        items=[item2, item1],  # Inverted order
        item_subtotal=100.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=100.00,
        currency="USD",
    )
    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    assert fp1 == fp2  # Deterministic multi-key sort guarantees hash match


# =====================================================================
# 3. Concurrency & Race Condition Protection
# =====================================================================

@pytest.mark.asyncio
async def test_concurrent_payment_execution_atomic_locking():
    """Simulate 5 simultaneous concurrent execution requests for the same checkout."""
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = AuthorizationPolicy(
        policy_id="pol_conc",
        version=1,
        user_id="usr_01",
        maximum_total=5000.00,
        automatic_purchase_limit=4000.00,
        allowed_currencies=["INR"],
    )
    coord.register_policy(policy)

    item = LineItem(sku="KB-K2", name="Keyboard", quantity=1, unit_price=3500.00)
    proposal = PurchaseProposal(
        proposal_id="prop_conc",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        merchant="Keychron India",
        items=[item],
        item_subtotal=3500.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=3500.00,
        currency="INR",
    )
    session = coord.create_proposal_session(proposal, policy)
    assert session.state == TransactionState.AUTHORIZED

    # Fire 5 concurrent executions of the exact same checkout_id at the exact same millisecond
    tasks = [
        coord.execute_payment(session.checkout_id)
        for _ in range(5)
    ]
    results = await asyncio.gather(*tasks)

    # All 5 return gracefully
    for r in results:
        assert r.state == TransactionState.PAID
        assert r.paypal_order_id == session.paypal_order_id

    # Check audit ledger: exactly ONE payment capture event, others deduplicated!
    events = coord.audit_ledger.get_events(checkout_id=session.checkout_id)
    payment_captures = [e for e in events if e.event_type == "PAYMENT_COMPLETED"]
    assert len(payment_captures) == 1

    dup_blocks = [e for e in events if e.event_type == "DUPLICATE_EXECUTION_BLOCKED"]
    assert len(dup_blocks) == 4


# =====================================================================
# 4. Lifecycle Invalidation & Expiry Edge Cases
# =====================================================================

def test_policy_revoked_while_user_approval_pending():
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = AuthorizationPolicy(
        policy_id="pol_rev",
        version=1,
        user_id="usr_01",
        maximum_total=5000.00,
        automatic_purchase_limit=4000.00,
        allowed_currencies=["INR"],
    )
    coord.register_policy(policy)

    item = LineItem(sku="KB-Q1", name="Keyboard", quantity=1, unit_price=4500.00)
    proposal = PurchaseProposal(
        proposal_id="prop_rev",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        merchant="Keychron India",
        items=[item],
        item_subtotal=4500.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=4500.00,
        currency="INR",
    )
    session = coord.create_proposal_session(proposal, policy)
    assert session.state == TransactionState.AWAITING_APPROVAL

    # User explicitly approves proposal
    coord.approve_proposal(session.checkout_id, user_id="usr_01")
    assert session.state == TransactionState.AUTHORIZED

    # But then user revokes policy before payment execution!
    coord.revoke_policy(policy.policy_id)

    # Pre-execution gate re-evaluates live policy and catches revocation
    loop = asyncio.new_event_loop()
    updated = loop.run_until_complete(coord.execute_payment(session.checkout_id))
    loop.close()

    assert updated.state == TransactionState.POLICY_REJECTED
    assert "revoked" in updated.failure_reason.lower()


def test_policy_version_bump_invalidates_stale_checkout():
    """User changes policy budget from 5000 to 3000 (bumps version to 2). Checkout was created under v1."""
    coord = TransactionCoordinator(paypal_client=PayPalClient(mock_mode=True))
    policy = AuthorizationPolicy(
        policy_id="pol_v",
        version=1,
        user_id="usr_01",
        maximum_total=5000.00,
        automatic_purchase_limit=4000.00,
        allowed_currencies=["INR"],
    )
    coord.register_policy(policy)

    item = LineItem(sku="KB-K2", name="Keyboard", quantity=1, unit_price=3800.00)
    proposal = PurchaseProposal(
        proposal_id="prop_v",
        policy_id=policy.policy_id,
        policy_version=1,
        merchant="Keychron India",
        items=[item],
        item_subtotal=3800.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=3800.00,
        currency="INR",
    )
    session = coord.create_proposal_session(proposal, policy)
    assert session.state == TransactionState.AUTHORIZED

    # Update policy to version 2
    updated_policy = copy.deepcopy(policy)
    updated_policy.maximum_total = 3000.00
    coord.update_policy(updated_policy)

    # Execute checkout prepared under v1
    loop = asyncio.new_event_loop()
    updated = loop.run_until_complete(coord.execute_payment(session.checkout_id))
    loop.close()

    assert updated.state == TransactionState.POLICY_REJECTED
    assert "version mismatch" in updated.failure_reason.lower()


def test_policy_expiry_boundary_conditions():
    now = datetime.now(timezone.utc)
    policy = AuthorizationPolicy(
        policy_id="pol_exp",
        version=1,
        user_id="usr",
        maximum_total=5000.0,
        automatic_purchase_limit=4000.0,
        expires_at=now,  # expires exactly now
    )
    item = LineItem(sku="KB-1", name="K", quantity=1, unit_price=100.0)
    proposal = PurchaseProposal(
        proposal_id="p1",
        policy_id="pol_exp",
        policy_version=1,
        merchant="M",
        items=[item],
        item_subtotal=100.0,
        shipping_fee=0.0,
        tax_fee=0.0,
        total_amount=100.0,
        currency="INR",
    )
    # 1 second before expiry: PASS
    res_before = DeterministicPolicyEngine.evaluate(
        proposal, policy, current_time=now - timedelta(seconds=1)
    )
    assert res_before.decision == PolicyDecisionType.ALLOW

    # 1 second after expiry: REJECT
    res_after = DeterministicPolicyEngine.evaluate(
        proposal, policy, current_time=now + timedelta(seconds=1)
    )
    assert res_after.decision == PolicyDecisionType.REJECT
    assert "expired" in res_after.primary_reason.lower()


# =====================================================================
# 5. Cryptographic Audit Ledger Tamper Detection
# =====================================================================

def test_audit_ledger_detects_tampered_event_data():
    ledger = AuditLedger()
    ledger.record_event(event_type="EVENT_1", reason="Reason 1")
    e2 = ledger.record_event(event_type="EVENT_2", reason="Reason 2")
    ledger.record_event(event_type="EVENT_3", reason="Reason 3")

    assert ledger.verify_ledger_integrity() is True

    # Attacker alters the reason of event 2 in the database
    e2.reason = "Tampered fraudulent reason"
    assert ledger.verify_ledger_integrity() is False


def test_audit_ledger_detects_deleted_intermediate_event():
    ledger = AuditLedger()
    ledger.record_event(event_type="EVENT_1")
    ledger.record_event(event_type="EVENT_2")
    ledger.record_event(event_type="EVENT_3")

    assert ledger.verify_ledger_integrity() is True

    # Attacker deletes event 2 to hide an unauthorized action
    ledger._events.pop(1)
    # Event 3's prev_event_hash will point to Event 2, which is now missing!
    assert ledger.verify_ledger_integrity() is False


def test_audit_ledger_detects_reordered_events():
    ledger = AuditLedger()
    ledger.record_event(event_type="EVENT_1")
    ledger.record_event(event_type="EVENT_2")
    ledger.record_event(event_type="EVENT_3")

    assert ledger.verify_ledger_integrity() is True

    # Attacker swaps event 1 and 2
    ledger._events[0], ledger._events[1] = ledger._events[1], ledger._events[0]
    assert ledger.verify_ledger_integrity() is False
