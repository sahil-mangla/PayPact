from datetime import datetime, timezone
from typing import List, Optional

from app.fingerprint.canonical import (
    compute_proposal_fingerprint,
    verify_proposal_fingerprint,
)
from app.models.schemas import (
    AuthorizationPolicy,
    IntegrityCheckResult,
    PolicyDecisionType,
    PolicyEvaluationResult,
    PurchaseProposal,
)


class DeterministicPolicyEngine:
    """Pure deterministic policy evaluation engine.

    Operates without language models or probabilistic inference.
    Fails closed on any ambiguity, math error, version mismatch, or limit violation.
    """

    @classmethod
    def evaluate(
        cls,
        proposal: PurchaseProposal,
        policy: AuthorizationPolicy,
        current_time: Optional[datetime] = None,
    ) -> PolicyEvaluationResult:
        """Evaluate a purchase proposal against an authorization policy."""
        now = current_time or datetime.now(timezone.utc)
        fingerprint = compute_proposal_fingerprint(proposal)
        checks: List[IntegrityCheckResult] = []

        # 1. Revocation Check
        if policy.is_revoked:
            checks.append(
                IntegrityCheckResult(
                    check_name="revocation_check",
                    passed=False,
                    reason=f"Policy '{policy.policy_id}' has been revoked by user.",
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=f"Policy '{policy.policy_id}' is revoked.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="revocation_check",
                passed=True,
                reason="Policy is active (not revoked).",
            )
        )

        # 2. Expiration Check
        if policy.expires_at is not None and now > policy.expires_at:
            checks.append(
                IntegrityCheckResult(
                    check_name="expiration_check",
                    passed=False,
                    reason=f"Policy expired at {policy.expires_at.isoformat()}.",
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="Authorization policy has expired.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="expiration_check",
                passed=True,
                reason="Policy has not expired.",
            )
        )

        # 3. Policy ID and Version Match
        if proposal.policy_id != policy.policy_id:
            checks.append(
                IntegrityCheckResult(
                    check_name="policy_id_check",
                    passed=False,
                    reason=f"Proposal targets policy '{proposal.policy_id}', but evaluated against '{policy.policy_id}'.",
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="Policy ID mismatch.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="policy_id_check",
                passed=True,
                reason="Policy ID matches.",
            )
        )

        if proposal.policy_version != policy.version:
            checks.append(
                IntegrityCheckResult(
                    check_name="policy_version_check",
                    passed=False,
                    reason=(
                        f"Proposal prepared under policy version {proposal.policy_version}, "
                        f"but active policy is version {policy.version}."
                    ),
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=f"Policy version mismatch ({proposal.policy_version} vs active {policy.version}).",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="policy_version_check",
                passed=True,
                reason=f"Policy version matches active version {policy.version}.",
            )
        )

        # 4. Currency Whitelist Check
        if proposal.currency.upper() not in [
            c.upper() for c in policy.allowed_currencies
        ]:
            checks.append(
                IntegrityCheckResult(
                    check_name="currency_check",
                    passed=False,
                    reason=f"Currency '{proposal.currency}' not in allowed currencies: {policy.allowed_currencies}.",
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=f"Currency '{proposal.currency}' is not authorized.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="currency_check",
                passed=True,
                reason=f"Currency '{proposal.currency}' is authorized.",
            )
        )

        # 5. Merchant Whitelist Check (if configured)
        if policy.allowed_merchants:
            allowed_norm = [m.strip().lower() for m in policy.allowed_merchants]
            if proposal.merchant.strip().lower() not in allowed_norm:
                checks.append(
                    IntegrityCheckResult(
                        check_name="merchant_check",
                        passed=False,
                        reason=f"Merchant '{proposal.merchant}' not in allowed merchants: {policy.allowed_merchants}.",
                    )
                )
                return PolicyEvaluationResult(
                    decision=PolicyDecisionType.REJECT,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    proposal_fingerprint=fingerprint,
                    checks=checks,
                    primary_reason=f"Merchant '{proposal.merchant}' is not authorized.",
                    evaluated_at=now,
                )
        checks.append(
            IntegrityCheckResult(
                check_name="merchant_check",
                passed=True,
                reason=f"Merchant '{proposal.merchant}' is authorized.",
            )
        )

        # 6. Line Item Sum Validation (Subtotal Integrity)
        calculated_subtotal = round(
            sum(item.quantity * item.unit_price for item in proposal.items), 2
        )
        if calculated_subtotal != round(proposal.item_subtotal, 2):
            checks.append(
                IntegrityCheckResult(
                    check_name="subtotal_integrity_check",
                    passed=False,
                    reason=(
                        f"Calculated line-item sum ({calculated_subtotal}) does not match "
                        f"proposal item_subtotal ({proposal.item_subtotal})."
                    ),
                    metadata={
                        "calculated": calculated_subtotal,
                        "stated": proposal.item_subtotal,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="Line-item subtotal calculation mismatch.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="subtotal_integrity_check",
                passed=True,
                reason=f"Subtotal calculation verified ({calculated_subtotal}).",
            )
        )

        # 7. Total Amount Sum Validation (Total Integrity)
        calculated_total = round(
            proposal.item_subtotal + proposal.shipping_fee + proposal.tax_fee, 2
        )
        if calculated_total != round(proposal.total_amount, 2):
            checks.append(
                IntegrityCheckResult(
                    check_name="total_integrity_check",
                    passed=False,
                    reason=(
                        f"Calculated total ({calculated_total}) does not match "
                        f"proposal total_amount ({proposal.total_amount})."
                    ),
                    metadata={
                        "calculated": calculated_total,
                        "stated": proposal.total_amount,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="Total amount sum calculation mismatch.",
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="total_integrity_check",
                passed=True,
                reason=f"Total amount verified ({calculated_total}).",
            )
        )

        # 8. Maximum Total Budget Check (Ceiling)
        if proposal.total_amount > policy.maximum_total:
            checks.append(
                IntegrityCheckResult(
                    check_name="maximum_budget_check",
                    passed=False,
                    reason=(
                        f"Total amount ({proposal.total_amount:.2f} {proposal.currency}) exceeds "
                        f"maximum authorized budget ({policy.maximum_total:.2f} {proposal.currency})."
                    ),
                    metadata={
                        "amount": proposal.total_amount,
                        "max_budget": policy.maximum_total,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=(
                    f"Exceeds maximum authorized budget ({proposal.total_amount:.2f} > {policy.maximum_total:.2f})."
                ),
                evaluated_at=now,
            )
        checks.append(
            IntegrityCheckResult(
                check_name="maximum_budget_check",
                passed=True,
                reason=(
                    f"Total amount ({proposal.total_amount:.2f}) within maximum budget ({policy.maximum_total:.2f})."
                ),
            )
        )

        # 8b. Cumulative Master Spend Check
        remaining_master_budget = round(policy.maximum_total - policy.spent_total, 2)
        if policy.spent_total > 0 and proposal.total_amount > remaining_master_budget:
            checks.append(
                IntegrityCheckResult(
                    check_name="master_cumulative_budget_check",
                    passed=False,
                    reason=(
                        f"Proposal amount ({proposal.total_amount:.2f}) exceeds remaining master budget "
                        f"({remaining_master_budget:.2f} of {policy.maximum_total:.2f})."
                    ),
                    metadata={
                        "remaining": remaining_master_budget,
                        "proposal_amount": proposal.total_amount,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REJECT,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=f"Exceeds remaining master budget ({proposal.total_amount:.2f} > {remaining_master_budget:.2f}).",
                evaluated_at=now,
            )

        # 8c. Agent Persona Swarm Quota Check (if agent_quotas configured)
        if policy.agent_quotas and proposal.agent_id:
            quota = policy.agent_quotas.get(proposal.agent_id)
            if not quota:
                checks.append(
                    IntegrityCheckResult(
                        check_name="agent_quota_check",
                        passed=False,
                        reason=f"Agent persona '{proposal.agent_id}' is not registered under policy quotas.",
                    )
                )
                return PolicyEvaluationResult(
                    decision=PolicyDecisionType.REJECT,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    proposal_fingerprint=fingerprint,
                    checks=checks,
                    primary_reason=f"Agent '{proposal.agent_id}' not authorized in swarm.",
                    evaluated_at=now,
                )
            if not quota.is_active:
                checks.append(
                    IntegrityCheckResult(
                        check_name="agent_quota_check",
                        passed=False,
                        reason=f"Agent persona '{proposal.agent_id}' is currently deactivated.",
                    )
                )
                return PolicyEvaluationResult(
                    decision=PolicyDecisionType.REJECT,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    proposal_fingerprint=fingerprint,
                    checks=checks,
                    primary_reason=f"Agent '{proposal.agent_id}' is deactivated.",
                    evaluated_at=now,
                )
            if proposal.total_amount > quota.remaining_budget:
                checks.append(
                    IntegrityCheckResult(
                        check_name="agent_quota_check",
                        passed=False,
                        reason=(
                            f"Proposal amount ({proposal.total_amount:.2f}) exceeds agent '{quota.agent_name}' "
                            f"remaining quota ({quota.remaining_budget:.2f} of {quota.allocated_budget:.2f})."
                        ),
                        metadata={
                            "remaining": quota.remaining_budget,
                            "proposal_amount": proposal.total_amount,
                        },
                    )
                )
                return PolicyEvaluationResult(
                    decision=PolicyDecisionType.REJECT,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    proposal_fingerprint=fingerprint,
                    checks=checks,
                    primary_reason=f"Exceeds agent '{quota.agent_name}' quota ({proposal.total_amount:.2f} > {quota.remaining_budget:.2f}).",
                    evaluated_at=now,
                )
            checks.append(
                IntegrityCheckResult(
                    check_name="agent_quota_check",
                    passed=True,
                    reason=f"Agent '{quota.agent_name}' has sufficient quota ({quota.remaining_budget:.2f} remaining).",
                )
            )

        # 9. Automatic Purchase Threshold Check
        if proposal.total_amount <= policy.automatic_purchase_limit:
            checks.append(
                IntegrityCheckResult(
                    check_name="automatic_limit_check",
                    passed=True,
                    reason=(
                        f"Total amount ({proposal.total_amount:.2f}) is within automatic purchase "
                        f"threshold ({policy.automatic_purchase_limit:.2f})."
                    ),
                    metadata={
                        "amount": proposal.total_amount,
                        "auto_limit": policy.automatic_purchase_limit,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.ALLOW,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="All integrity checks passed. Permitted for automatic execution.",
                evaluated_at=now,
            )

        # Exceeds automatic purchase limit but <= maximum budget
        if policy.require_approval_above_limit:
            checks.append(
                IntegrityCheckResult(
                    check_name="automatic_limit_check",
                    passed=False,
                    reason=(
                        f"Total amount ({proposal.total_amount:.2f}) exceeds automatic purchase "
                        f"limit ({policy.automatic_purchase_limit:.2f}). User approval required."
                    ),
                    metadata={
                        "amount": proposal.total_amount,
                        "auto_limit": policy.automatic_purchase_limit,
                    },
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason=(
                    f"Exceeds automatic limit ({proposal.total_amount:.2f} > {policy.automatic_purchase_limit:.2f}). "
                    f"Explicit user approval required."
                ),
                evaluated_at=now,
            )
        else:
            # If explicit approval is not configured, allow within max budget
            checks.append(
                IntegrityCheckResult(
                    check_name="automatic_limit_check",
                    passed=True,
                    reason="Within maximum budget, explicit approval not required by policy.",
                )
            )
            return PolicyEvaluationResult(
                decision=PolicyDecisionType.ALLOW,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                proposal_fingerprint=fingerprint,
                checks=checks,
                primary_reason="Permitted for execution under maximum budget.",
                evaluated_at=now,
            )

    @classmethod
    def revalidate_pre_execution(
        cls,
        proposal: PurchaseProposal,
        policy: AuthorizationPolicy,
        approved_fingerprint: Optional[str] = None,
        current_time: Optional[datetime] = None,
    ) -> PolicyEvaluationResult:
        """Lifecycle Revalidation Gate immediately prior to PayPal execution.

        Guarantees that:
        1. If user previously approved this proposal, the proposal has not drifted by even 1 cent or SKU.
        2. The policy has not been revoked or updated in the interim.
        3. All boundary limits still hold.
        """
        now = current_time or datetime.now(timezone.utc)
        current_fingerprint = compute_proposal_fingerprint(proposal)

        # If user explicitly approved an earlier fingerprint, verify exact match
        if approved_fingerprint is not None:
            if not verify_proposal_fingerprint(proposal, approved_fingerprint):
                checks = [
                    IntegrityCheckResult(
                        check_name="approved_fingerprint_match",
                        passed=False,
                        reason=(
                            f"Proposal data drifted after user approval! "
                            f"Approved: {approved_fingerprint[:12]}..., Current: {current_fingerprint[:12]}..."
                        ),
                        metadata={
                            "approved_fingerprint": approved_fingerprint,
                            "current_fingerprint": current_fingerprint,
                        },
                    )
                ]
                return PolicyEvaluationResult(
                    decision=PolicyDecisionType.REJECT,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    proposal_fingerprint=current_fingerprint,
                    checks=checks,
                    primary_reason="Proposal details drifted after user approval was granted.",
                    evaluated_at=now,
                )

        # Re-run full policy evaluation against current policy
        return cls.evaluate(proposal=proposal, policy=policy, current_time=now)
