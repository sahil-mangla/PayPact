import asyncio
import math
import re
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from app.audit.ledger import AuditLedger
from app.crypto.receipts import generate_signed_receipt
from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    ApprovalRecord,
    AuthorizationPolicy,
    PolicyDecisionType,
    PurchaseProposal,
    SignedAuditReceipt,
    TransactionState,
)
from app.payments.paypal_client import PayPalClient, PayPalOrderResponse
from app.policy.engine import DeterministicPolicyEngine


# PayPal order ids are short alphanumeric tokens; anything else never reaches a PayPal URL.
ORDER_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


class CheckoutSession(BaseModel):
    checkout_id: str
    policy_id: str
    policy_version: int
    proposal: PurchaseProposal
    state: TransactionState
    approved_fingerprint: Optional[str] = None
    approval_record: Optional[ApprovalRecord] = None
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    failure_reason: Optional[str] = None
    reconciliation_data: Optional[Dict] = None
    refunded_total: float = 0.0


class TransactionCoordinator:
    """Manages the full transaction lifecycle and enforces safety guards."""

    def __init__(
        self,
        paypal_client: Optional[PayPalClient] = None,
        audit_ledger: Optional[AuditLedger] = None,
    ):
        self.paypal_client = paypal_client or PayPalClient()
        self.audit_ledger = audit_ledger or AuditLedger()
        self._sessions: Dict[str, CheckoutSession] = {}
        self._policies: Dict[str, AuthorizationPolicy] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> checkout_id
        self._execution_locks: Dict[str, asyncio.Lock] = {}
        # Webhook event ids already applied (insertion-ordered, bounded) so redelivery is a no-op.
        self._seen_webhook_events: Dict[str, None] = {}

    def _get_execution_lock(self, checkout_id: str) -> asyncio.Lock:
        if checkout_id not in self._execution_locks:
            self._execution_locks[checkout_id] = asyncio.Lock()
        return self._execution_locks[checkout_id]

    def register_policy(self, policy: AuthorizationPolicy) -> AuthorizationPolicy:
        self._policies[policy.policy_id] = policy
        self.audit_ledger.record_event(
            event_type="POLICY_REGISTERED",
            policy_version=policy.version,
            reason=f"Policy {policy.policy_id} registered (v{policy.version})",
            metadata={
                "maximum_total": policy.maximum_total,
                "auto_limit": policy.automatic_purchase_limit,
            },
        )
        return policy

    def get_policy(self, policy_id: str) -> Optional[AuthorizationPolicy]:
        return self._policies.get(policy_id)

    def revoke_policy(self, policy_id: str) -> bool:
        policy = self._policies.get(policy_id)
        if not policy:
            return False
        policy.is_revoked = True
        self.audit_ledger.record_event(
            event_type="POLICY_REVOKED",
            policy_version=policy.version,
            reason=f"Policy {policy_id} explicitly revoked by user",
        )
        return True

    def update_policy(self, updated_policy: AuthorizationPolicy) -> AuthorizationPolicy:
        """Update policy and increment revision version."""
        existing = self._policies.get(updated_policy.policy_id)
        if existing:
            updated_policy.version = existing.version + 1
        self._policies[updated_policy.policy_id] = updated_policy
        self.audit_ledger.record_event(
            event_type="POLICY_UPDATED",
            policy_version=updated_policy.version,
            reason=f"Policy {updated_policy.policy_id} updated to version {updated_policy.version}",
        )
        return updated_policy

    def create_proposal_session(
        self,
        proposal: PurchaseProposal,
        policy: AuthorizationPolicy,
    ) -> CheckoutSession:
        """Create a new checkout session and evaluate against policy."""
        checkout_id = f"chk_{uuid.uuid4().hex[:12]}"
        fp = proposal.proposal_fingerprint or compute_proposal_fingerprint(proposal)
        proposal.proposal_fingerprint = fp

        self.audit_ledger.record_event(
            event_type="PROPOSAL_CREATED",
            checkout_id=checkout_id,
            policy_version=policy.version,
            proposal_fingerprint=fp,
            metadata={"total": proposal.total_amount, "merchant": proposal.merchant},
        )

        # Evaluate deterministic policy
        eval_result = DeterministicPolicyEngine.evaluate(proposal, policy)

        if eval_result.decision == PolicyDecisionType.ALLOW:
            state = TransactionState.AUTHORIZED
        elif eval_result.decision == PolicyDecisionType.REQUIRE_APPROVAL:
            state = TransactionState.AWAITING_APPROVAL
        else:
            state = TransactionState.POLICY_REJECTED

        session = CheckoutSession(
            checkout_id=checkout_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            proposal=proposal,
            state=state,
            # An auto-authorized checkout is bound to the exact proposal the policy allowed,
            # so later drift is caught the same way as on a user-approved one.
            approved_fingerprint=fp if state == TransactionState.AUTHORIZED else None,
            failure_reason=eval_result.primary_reason
            if state == TransactionState.POLICY_REJECTED
            else None,
        )

        self._sessions[checkout_id] = session
        self._idempotency_map[session.idempotency_key] = checkout_id

        self.audit_ledger.record_event(
            event_type="POLICY_EVALUATED",
            checkout_id=checkout_id,
            policy_version=policy.version,
            proposal_fingerprint=fp,
            decision=eval_result.decision.value,
            reason=eval_result.primary_reason,
        )

        return session

    def approve_proposal(
        self,
        checkout_id: str,
        user_id: str,
    ) -> CheckoutSession:
        """User explicitly approves the proposal."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Checkout '{checkout_id}' not found.")

        if session.state not in (
            TransactionState.AWAITING_APPROVAL,
            TransactionState.AUTHORIZED,
        ):
            raise ValueError(
                f"Cannot approve checkout in state '{session.state}'. Must be AWAITING_APPROVAL or AUTHORIZED."
            )

        fp = session.proposal.proposal_fingerprint or compute_proposal_fingerprint(
            session.proposal
        )
        record = ApprovalRecord(
            approval_id=f"appr_{uuid.uuid4().hex[:8]}",
            proposal_id=session.proposal.proposal_id,
            proposal_fingerprint=fp,
            policy_version=session.policy_version,
            approved_by=user_id,
        )

        session.state = TransactionState.AUTHORIZED
        session.approved_fingerprint = fp
        session.approval_record = record

        self.audit_ledger.record_event(
            event_type="USER_APPROVED",
            checkout_id=checkout_id,
            policy_version=session.policy_version,
            proposal_fingerprint=fp,
            reason=f"User '{user_id}' explicitly approved exact proposal fingerprint",
        )

        return session

    async def execute_payment(
        self,
        checkout_id: str,
        current_proposal_state: Optional[PurchaseProposal] = None,
        idempotency_key: Optional[str] = None,
        simulate_timeout: bool = False,
    ) -> CheckoutSession:
        """Execute checkout with Pre-Execution Lifecycle Gate and duplicate protection."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Checkout '{checkout_id}' not found.")

        lock = self._get_execution_lock(checkout_id)
        async with lock:
            # 1. Idempotency Check: Already captured?
            if session.state == TransactionState.PAID:
                self.audit_ledger.record_event(
                    event_type="DUPLICATE_EXECUTION_BLOCKED",
                    checkout_id=checkout_id,
                    reason="Attempted to execute payment on already PAID checkout. Blocked safely.",
                )
                return session

            # Verify state is AUTHORIZED
            if session.state != TransactionState.AUTHORIZED:
                raise ValueError(
                    f"Cannot execute checkout in state '{session.state}'. Must be AUTHORIZED."
                )

            # 2. Pre-Execution Invariant Gate
            # Check against latest policy state and live merchant proposal data
            policy = self._policies.get(session.policy_id)
            if not policy:
                session.state = TransactionState.FAILED
                session.failure_reason = "Policy not found during pre-execution."
                return session

            # If live merchant data has drifted (e.g. price change, tax added), use it
            live_proposal = current_proposal_state or session.proposal

            reval = DeterministicPolicyEngine.revalidate_pre_execution(
                proposal=live_proposal,
                policy=policy,
                approved_fingerprint=session.approved_fingerprint,
                approval_granted=session.approval_record is not None,
            )

            if reval.decision != PolicyDecisionType.ALLOW:
                # Drift or revocation caught!
                session.state = TransactionState.POLICY_REJECTED
                session.failure_reason = reval.primary_reason
                self.audit_ledger.record_event(
                    event_type="PRE_EXECUTION_BLOCKED",
                    checkout_id=checkout_id,
                    policy_version=policy.version,
                    proposal_fingerprint=reval.proposal_fingerprint,
                    decision=reval.decision.value,
                    reason=reval.primary_reason,
                )
                return session

            # The gate only judges the live copy. Charge exactly what was proposed and
            # approved, never data that came in with the execute request.
            live_proposal = session.proposal

            # 3. Create PayPal Order
            req_id = idempotency_key or session.idempotency_key
            try:
                order_resp: PayPalOrderResponse = await self.paypal_client.create_order(
                    proposal=live_proposal,
                    request_id=req_id,
                )
                session.paypal_order_id = order_resp.order_id
                session.state = TransactionState.CHECKOUT_CREATED

                self.audit_ledger.record_event(
                    event_type="CHECKOUT_CREATED",
                    checkout_id=checkout_id,
                    policy_version=policy.version,
                    proposal_fingerprint=live_proposal.proposal_fingerprint,
                    reason=f"PayPal order created with ID {order_resp.order_id}",
                )
            except Exception as e:
                session.state = TransactionState.FAILED
                session.failure_reason = f"PayPal create order failed: {str(e)}"
                return session

            # 4. Capture Order
            if simulate_timeout:
                # Ambiguous timeout scenario (Scenario G)
                session.state = TransactionState.RECONCILIATION_REQUIRED
                session.failure_reason = (
                    "Network timeout during capture. Gateway state ambiguous."
                )
                self.audit_ledger.record_event(
                    event_type="PAYMENT_AMBIGUOUS_TIMEOUT",
                    checkout_id=checkout_id,
                    reason="Timeout during payment capture. Marked for reconciliation without blind retry.",
                )
                return session

            try:
                capture_resp: PayPalOrderResponse = (
                    await self.paypal_client.capture_order(
                        order_id=session.paypal_order_id,
                        request_id=f"{req_id}_cap",
                    )
                )
                if capture_resp.status == "COMPLETED":
                    session.state = TransactionState.PAID
                    session.paypal_capture_id = capture_resp.capture_id
                    self._record_spend(
                        policy_id=session.policy_id,
                        amount=live_proposal.total_amount,
                        agent_id=live_proposal.agent_id,
                    )
                    self.audit_ledger.record_event(
                        event_type="PAYMENT_COMPLETED",
                        checkout_id=checkout_id,
                        policy_version=policy.version,
                        proposal_fingerprint=live_proposal.proposal_fingerprint,
                        reason=f"Payment captured successfully with capture ID {capture_resp.capture_id}",
                    )
                else:
                    session.state = TransactionState.FAILED
                    session.failure_reason = (
                        f"PayPal returned status: {capture_resp.status}"
                    )
            except Exception as e:
                session.state = TransactionState.RECONCILIATION_REQUIRED
                session.failure_reason = f"PayPal capture error: {str(e)}"

            return session

    async def create_paypal_order_only(
        self,
        checkout_id: str,
        current_proposal_state: Optional[PurchaseProposal] = None,
        simulate_timeout: bool = False,
    ) -> CheckoutSession:
        """Live sandbox phase-1: Run pre-execution gate + create PayPal order.
        Does NOT capture — buyer must approve via JS SDK popup first."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Checkout '{checkout_id}' not found.")

        lock = self._get_execution_lock(checkout_id)
        async with lock:
            if session.state == TransactionState.PAID:
                return session

            # The buyer closed the PayPal popup and came back: hand back the same order
            # instead of failing, or creating a second one for the same checkout.
            if (
                session.state == TransactionState.CHECKOUT_CREATED
                and session.paypal_order_id
            ):
                return session

            if session.state != TransactionState.AUTHORIZED:
                raise ValueError(
                    f"Cannot execute checkout in state '{session.state}'. Must be AUTHORIZED."
                )

            policy = self._policies.get(session.policy_id)
            if not policy:
                session.state = TransactionState.FAILED
                session.failure_reason = "Policy not found during pre-execution."
                return session

            live_proposal = current_proposal_state or session.proposal

            # Pre-execution invariant gate
            reval = DeterministicPolicyEngine.revalidate_pre_execution(
                proposal=live_proposal,
                policy=policy,
                approved_fingerprint=session.approved_fingerprint,
                approval_granted=session.approval_record is not None,
            )

            if reval.decision != PolicyDecisionType.ALLOW:
                session.state = TransactionState.POLICY_REJECTED
                session.failure_reason = reval.primary_reason
                self.audit_ledger.record_event(
                    event_type="PRE_EXECUTION_BLOCKED",
                    checkout_id=checkout_id,
                    policy_version=policy.version,
                    proposal_fingerprint=reval.proposal_fingerprint,
                    decision=reval.decision.value,
                    reason=reval.primary_reason,
                )
                return session

            # The gate only judges the live copy. Charge exactly what was proposed and
            # approved, never data that came in with the execute request.
            live_proposal = session.proposal

            # Check timeout simulation for live sandbox
            if simulate_timeout:
                session.state = TransactionState.RECONCILIATION_REQUIRED
                session.failure_reason = (
                    "Network timeout during capture. Gateway state ambiguous."
                )
                self.audit_ledger.record_event(
                    event_type="PAYMENT_AMBIGUOUS_TIMEOUT",
                    checkout_id=checkout_id,
                    reason="Timeout during payment creation/capture. Marked for reconciliation without blind retry.",
                )
                return session

            # Create PayPal order (no capture yet)
            req_id = session.idempotency_key
            try:
                order_resp: PayPalOrderResponse = await self.paypal_client.create_order(
                    proposal=live_proposal,
                    request_id=req_id,
                )
                session.paypal_order_id = order_resp.order_id
                session.state = TransactionState.CHECKOUT_CREATED
                self.audit_ledger.record_event(
                    event_type="CHECKOUT_CREATED",
                    checkout_id=checkout_id,
                    policy_version=policy.version,
                    proposal_fingerprint=live_proposal.proposal_fingerprint,
                    reason=f"PayPal order created: {order_resp.order_id} — awaiting buyer approval",
                )
            except Exception as e:
                session.state = TransactionState.FAILED
                session.failure_reason = f"PayPal create order failed: {str(e)}"

            return session

    async def capture_approved_order(
        self,
        checkout_id: str,
        paypal_order_id: str,
    ) -> CheckoutSession:
        """Live sandbox phase-2: Capture after buyer approved via PayPal JS SDK popup."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Checkout '{checkout_id}' not found.")

        if not ORDER_ID_RE.fullmatch(paypal_order_id or ""):
            raise ValueError("Malformed PayPal order ID.")

        lock = self._get_execution_lock(checkout_id)
        async with lock:
            # Everything below runs under the lock, so a concurrent execute or capture
            # cannot change the state between the checks and the PayPal call.
            if (
                session.state == TransactionState.PAID
                and session.paypal_order_id == paypal_order_id
            ):
                return session

            if session.state != TransactionState.CHECKOUT_CREATED:
                raise ValueError(
                    f"Cannot capture checkout in state '{session.state}'. Must be CHECKOUT_CREATED."
                )

            # Only the order this checkout created may be captured through it.
            if not session.paypal_order_id or session.paypal_order_id != paypal_order_id:
                raise ValueError(
                    f"Order ID mismatch: expected '{session.paypal_order_id}', got '{paypal_order_id}'. "
                    "Potential tampering detected."
                )

            # The buyer approved in PayPal's popup some time after the gate ran. Policy
            # revocation or expiry in that window must still stop the money moving.
            policy = self._policies.get(session.policy_id)
            if not policy:
                session.state = TransactionState.FAILED
                session.failure_reason = "Policy not found during capture."
                return session
            reval = DeterministicPolicyEngine.revalidate_pre_execution(
                proposal=session.proposal,
                policy=policy,
                approved_fingerprint=session.approved_fingerprint,
                approval_granted=session.approval_record is not None,
            )
            if reval.decision != PolicyDecisionType.ALLOW:
                session.state = TransactionState.POLICY_REJECTED
                session.failure_reason = reval.primary_reason
                self.audit_ledger.record_event(
                    event_type="PRE_EXECUTION_BLOCKED",
                    checkout_id=checkout_id,
                    policy_version=policy.version,
                    proposal_fingerprint=reval.proposal_fingerprint,
                    decision=reval.decision.value,
                    reason=f"Blocked at capture: {reval.primary_reason}",
                )
                return session

            try:
                capture_resp: PayPalOrderResponse = (
                    await self.paypal_client.capture_order(
                        order_id=paypal_order_id,
                        request_id=f"{session.idempotency_key}_cap",
                    )
                )
                if capture_resp.status == "COMPLETED":
                    session.state = TransactionState.PAID
                    session.paypal_capture_id = capture_resp.capture_id
                    self._record_spend(
                        policy_id=session.policy_id,
                        amount=session.proposal.total_amount,
                        agent_id=session.proposal.agent_id,
                    )
                    self.audit_ledger.record_event(
                        event_type="PAYMENT_COMPLETED",
                        checkout_id=checkout_id,
                        reason=f"Live sandbox capture successful. Capture ID: {capture_resp.capture_id}",
                    )
                else:
                    session.state = TransactionState.FAILED
                    session.failure_reason = (
                        f"PayPal returned unexpected status: {capture_resp.status}"
                    )
            except Exception as e:
                session.state = TransactionState.RECONCILIATION_REQUIRED
                session.failure_reason = f"PayPal capture error: {str(e)}"

            return session

    async def reconcile_timeout(self, checkout_id: str) -> CheckoutSession:
        """Reconcile ambiguous timeout with PayPal."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Cannot reconcile checkout '{checkout_id}'.")

        async with self._get_execution_lock(checkout_id):
            # Already settled: reconciling again must never touch the budget a second time.
            if session.state == TransactionState.PAID:
                return session

            if session.state != TransactionState.RECONCILIATION_REQUIRED:
                raise ValueError(
                    f"Cannot reconcile checkout in state '{session.state}'. "
                    "Must be RECONCILIATION_REQUIRED."
                )

            if not session.paypal_order_id:
                # The timeout hit before PayPal returned an order, so nothing can have been charged.
                session.state = TransactionState.FAILED
                session.failure_reason = "No PayPal order was created before the timeout."
                self.audit_ledger.record_event(
                    event_type="RECONCILIATION_ABORT",
                    checkout_id=checkout_id,
                    reason="No PayPal order exists for this checkout. Safe to abort without charge.",
                )
                return session

            details = await self.paypal_client.get_order_details(
                session.paypal_order_id
            )
            session.reconciliation_data = details.raw_response

            if details.status == "COMPLETED":
                session.state = TransactionState.PAID
                session.paypal_capture_id = details.capture_id
                self._record_spend(
                    policy_id=session.policy_id,
                    amount=session.proposal.total_amount,
                    agent_id=session.proposal.agent_id,
                )
                self.audit_ledger.record_event(
                    event_type="RECONCILIATION_SUCCESS",
                    checkout_id=checkout_id,
                    reason="Order reconciled as COMPLETED via PayPal lookup.",
                )
            else:
                session.state = TransactionState.FAILED
                session.failure_reason = (
                    f"Order reconciled as non-captured ({details.status})."
                )
                self.audit_ledger.record_event(
                    event_type="RECONCILIATION_ABORT",
                    checkout_id=checkout_id,
                    reason=f"Order reconciled as {details.status}. Safe to abort without duplicate charge.",
                )

            return session

    def get_session(self, checkout_id: str) -> Optional[CheckoutSession]:
        return self._sessions.get(checkout_id)

    def _record_spend(
        self, policy_id: str, amount: float, agent_id: Optional[str] = None
    ):
        """Atomically record captured spend against master policy and agent quota."""
        policy = self._policies.get(policy_id)
        if policy:
            policy.spent_total = round(policy.spent_total + amount, 2)
            if agent_id and policy.agent_quotas and agent_id in policy.agent_quotas:
                quota = policy.agent_quotas[agent_id]
                quota.spent_budget = round(quota.spent_budget + amount, 2)

    def _record_refund(
        self, policy_id: str, amount: float, agent_id: Optional[str] = None
    ):
        """Atomically credit back spend on refund or merchant reversal."""
        policy = self._policies.get(policy_id)
        if policy:
            policy.spent_total = round(max(0.0, policy.spent_total - amount), 2)
            if agent_id and policy.agent_quotas and agent_id in policy.agent_quotas:
                quota = policy.agent_quotas[agent_id]
                quota.spent_budget = round(max(0.0, quota.spent_budget - amount), 2)

    def _find_checkout_for_resource(self, resource: Dict[str, Any]) -> Optional[str]:
        """Match a PayPal webhook resource to a checkout by order or capture id.

        PAYMENT.CAPTURE.REFUNDED carries the refund's own id in `resource.id`; the order
        and capture it belongs to are in `supplementary_data` and the `up` link.
        """
        candidates = {resource.get("id"), resource.get("order_id")}
        related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
        candidates.add(related.get("order_id"))
        for link in resource.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "up":
                href = str(link.get("href") or "")
                candidates.add(href.rstrip("/").rsplit("/", 1)[-1])
        candidates.discard(None)
        candidates.discard("")
        for chk_id, sess in self._sessions.items():
            if (
                sess.paypal_order_id in candidates
                or sess.paypal_capture_id in candidates
            ):
                return chk_id
        return None

    @staticmethod
    def _parse_refund_amount(resource: Dict[str, Any], default: float) -> Optional[float]:
        """Positive finite refund amount, or None when the payload is unusable."""
        amount_dict = resource.get("amount") or {}
        raw = amount_dict.get("value")
        if raw is None:
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return round(value, 2)

    async def process_webhook_event(
        self,
        event_type: str,
        resource: Dict[str, Any],
        checkout_id: Optional[str] = None,
        summary: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Optional[CheckoutSession]:
        """Process asynchronous PayPal webhook events (refunds, disputes, reversals)."""
        target_checkout_id = checkout_id or self._find_checkout_for_resource(resource)
        if not target_checkout_id or target_checkout_id not in self._sessions:
            return None

        session = self._sessions[target_checkout_id]
        policy = self._policies.get(session.policy_id)

        # PayPal redelivers webhooks, and anyone can replay a captured one: apply each event once.
        if event_id:
            if event_id in self._seen_webhook_events:
                return session
            self._seen_webhook_events[event_id] = None
            if len(self._seen_webhook_events) > 10_000:
                self._seen_webhook_events.pop(next(iter(self._seen_webhook_events)))

        async with self._get_execution_lock(target_checkout_id):
            if event_type in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.SALE.REFUNDED"):
                self._apply_refund(session, policy, resource, summary)
            elif event_type in (
                "CUSTOMER.DISPUTE.CREATED",
                "PAYMENT.CAPTURE.REVERSED",
            ):
                if session.state == TransactionState.PAID:
                    session.state = TransactionState.DISPUTED
                    self.audit_ledger.record_event(
                        event_type="PAYMENT_DISPUTED",
                        checkout_id=target_checkout_id,
                        policy_version=policy.version if policy else None,
                        reason=summary
                        or f"Payment disputed via PayPal webhook: {event_type}",
                    )
        return session

    def _apply_refund(
        self,
        session: CheckoutSession,
        policy: Optional[AuthorizationPolicy],
        resource: Dict[str, Any],
        summary: Optional[str],
    ) -> None:
        # Money can only come back for a checkout that actually captured it.
        if session.state != TransactionState.PAID:
            return
        outstanding = round(session.proposal.total_amount - session.refunded_total, 2)
        requested = self._parse_refund_amount(resource, default=outstanding)
        if requested is None:
            return
        credit = min(requested, outstanding)
        if credit <= 0:
            return

        session.refunded_total = round(session.refunded_total + credit, 2)
        self._record_refund(
            policy_id=session.policy_id,
            amount=credit,
            agent_id=session.proposal.agent_id,
        )
        fully_refunded = session.refunded_total >= session.proposal.total_amount
        if fully_refunded:
            session.state = TransactionState.REFUNDED
        self.audit_ledger.record_event(
            event_type="PAYMENT_REFUNDED"
            if fully_refunded
            else "PAYMENT_PARTIALLY_REFUNDED",
            checkout_id=session.checkout_id,
            policy_version=policy.version if policy else None,
            reason=summary
            or f"Payment refunded for checkout {session.checkout_id}: {credit}",
        )

    def generate_audit_receipt(self, checkout_id: str) -> SignedAuditReceipt:
        """Generate tamper-evident, digitally signed audit receipt for a checkout session."""
        session = self._sessions.get(checkout_id)
        if not session:
            raise ValueError(f"Checkout '{checkout_id}' not found.")

        return generate_signed_receipt(
            checkout_id=checkout_id,
            decision="ALLOW"
            if session.state == TransactionState.PAID
            else "REJECT_OR_BLOCKED",
            status=session.state.value,
            policy_id=session.policy_id,
            policy_version=session.policy_version,
            proposal_fingerprint=session.proposal.proposal_fingerprint or "",
            total_amount=session.proposal.total_amount,
            currency=session.proposal.currency,
            merchant=session.proposal.merchant,
            items_count=len(session.proposal.items),
            agent_id=session.proposal.agent_id,
            paypal_order_id=session.paypal_order_id,
            paypal_capture_id=session.paypal_capture_id,
        )
