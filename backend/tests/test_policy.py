from datetime import datetime, timedelta, timezone
import pytest

from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    AuthorizationPolicy,
    LineItem,
    PolicyDecisionType,
    PurchaseProposal,
)
from app.policy.engine import DeterministicPolicyEngine


@pytest.fixture
def default_policy() -> AuthorizationPolicy:
    return AuthorizationPolicy(
        policy_id="pol_001",
        version=1,
        user_id="usr_01",
        product_category="mechanical keyboard",
        maximum_total=5000.00,
        automatic_purchase_limit=4000.00,
        allowed_currencies=["INR", "USD"],
        allowed_merchants=["Keychron India", "Meckeys"],
        require_approval_above_limit=True,
        is_revoked=False,
    )


def make_proposal(
    policy_id: str = "pol_001",
    version: int = 1,
    price: float = 3899.00,
    shipping: float = 0.00,
    tax: float = 0.00,
    stated_subtotal: float = 3899.00,
    stated_total: float = 3899.00,
    merchant: str = "Keychron India",
    currency: str = "INR",
    sku: str = "KB-K2-RGB",
) -> PurchaseProposal:
    item = LineItem(sku=sku, name="Mechanical Keyboard", quantity=1, unit_price=price)
    return PurchaseProposal(
        proposal_id="prop_001",
        policy_id=policy_id,
        policy_version=version,
        merchant=merchant,
        items=[item],
        item_subtotal=stated_subtotal,
        shipping_fee=shipping,
        tax_fee=tax,
        total_amount=stated_total,
        currency=currency,
    )


def test_happy_path_automatic_allow(default_policy):
    # Total 3899 is below auto limit 4000 and max 5000 -> ALLOW
    proposal = make_proposal(
        price=3899.00, stated_subtotal=3899.00, stated_total=3899.00
    )
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.ALLOW
    assert all(c.passed for c in result.checks)
    assert result.proposal_fingerprint is not None


def test_happy_path_require_approval(default_policy):
    # Total 4500 is above auto limit 4000 but below max budget 5000 -> REQUIRE_APPROVAL
    proposal = make_proposal(
        price=4500.00, stated_subtotal=4500.00, stated_total=4500.00
    )
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REQUIRE_APPROVAL
    # The automatic limit check failed, but maximum budget passed
    auto_check = next(
        c for c in result.checks if c.check_name == "automatic_limit_check"
    )
    assert auto_check.passed is False


def test_rejects_exceeding_maximum_budget(default_policy):
    # Total 5200 exceeds max budget 5000 -> REJECT
    proposal = make_proposal(
        price=5200.00, stated_subtotal=5200.00, stated_total=5200.00
    )
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "maximum" in result.primary_reason.lower()


def test_rejects_arithmetic_subtotal_tamper(default_policy):
    # 1 item of 3899, but proposal claims subtotal is 2000 -> REJECT
    proposal = make_proposal(
        price=3899.00, stated_subtotal=2000.00, stated_total=2000.00
    )
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "subtotal" in result.primary_reason.lower()


def test_rejects_arithmetic_total_tamper(default_policy):
    # subtotal 3899 + shipping 500 = 4399, but proposal claims total is 3899 -> REJECT
    proposal = make_proposal(
        price=3899.00, shipping=500.00, stated_subtotal=3899.00, stated_total=3899.00
    )
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "total" in result.primary_reason.lower()


def test_rejects_revoked_policy(default_policy):
    default_policy.is_revoked = True
    proposal = make_proposal(price=3899.00)
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "revoked" in result.primary_reason.lower()


def test_rejects_expired_policy(default_policy):
    past_time = datetime.now(timezone.utc) - timedelta(hours=1)
    default_policy.expires_at = past_time
    proposal = make_proposal(price=3899.00)
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "expired" in result.primary_reason.lower()


def test_rejects_policy_version_mismatch(default_policy):
    # Active policy is version 1, but proposal prepared for version 2
    proposal = make_proposal(version=2)
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "version" in result.primary_reason.lower()


def test_rejects_unauthorized_currency(default_policy):
    # Policy only allows INR and USD, proposal requests EUR
    proposal = make_proposal(currency="EUR")
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "currency" in result.primary_reason.lower()


def test_rejects_unauthorized_merchant(default_policy):
    # Allowed: Keychron India, Meckeys. Proposal: UntrustedStore
    proposal = make_proposal(merchant="UntrustedStore")
    result = DeterministicPolicyEngine.evaluate(proposal, default_policy)

    assert result.decision == PolicyDecisionType.REJECT
    assert "merchant" in result.primary_reason.lower()


def test_pre_execution_detects_drift_after_approval(default_policy):
    # User approved proposal at 4500 (fingerprint fp1)
    proposal_approved = make_proposal(
        price=4500.00, stated_subtotal=4500.00, stated_total=4500.00
    )
    approved_fp = compute_proposal_fingerprint(proposal_approved)

    # Immediately before execution, merchant added 300 shipping
    proposal_drifted = make_proposal(
        price=4500.00, shipping=300.00, stated_subtotal=4500.00, stated_total=4800.00
    )

    reval = DeterministicPolicyEngine.revalidate_pre_execution(
        proposal=proposal_drifted,
        policy=default_policy,
        approved_fingerprint=approved_fp,
    )

    assert reval.decision == PolicyDecisionType.REJECT
    assert "drifted" in reval.primary_reason.lower()
