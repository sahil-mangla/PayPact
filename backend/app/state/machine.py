import asyncio
import uuid
from typing import Dict, Optional
from pydantic import BaseModel, Field

from app.audit.ledger import AuditLedger
from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    ApprovalRecord,
    AuthorizationPolicy,
    PolicyDecisionType,
    PurchaseProposal,
    TransactionState,
)
from app.payments.paypal_client import PayPalClient, PayPalOrderResponse
from app.policy.engine import DeterministicPolicyEngine


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

    def register_policy(self, policy: AuthorizationPolicy) -> AuthorizationPolicy:
        self._policies[policy.policy_id] = policy
        self.audit_ledger.record_event(
            event_type="POLICY_REGISTERED",
            policy_version=policy.version,
            reason=f"Policy {policy.policy_id} registered (v{policy.version})",
            metadata={"maximum_total": policy.maximum_total, "auto_limit": policy.automatic_purchase_limit},
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
            failure_reason=eval_result.primary_reason if state == TransactionState.POLICY_REJECTED else None,
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

        if session.state not in (TransactionState.AWAITING_APPROVAL, TransactionState.AUTHORIZED):
            raise ValueError(
                f"Cannot approve checkout in state '{session.state}'. Must be AWAITING_APPROVAL or AUTHORIZED."
            )

        fp = session.proposal.proposal_fingerprint or compute_proposal_fingerprint(session.proposal)
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

        if checkout_id not in self._execution_locks:
            self._execution_locks[checkout_id] = asyncio.Lock()

        async with self._execution_locks[checkout_id]:
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
                raise ValueError(f"Cannot execute checkout in state '{session.state}'. Must be AUTHORIZED.")

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
                session.failure_reason = "Network timeout during capture. Gateway state ambiguous."
                self.audit_ledger.record_event(
                    event_type="PAYMENT_AMBIGUOUS_TIMEOUT",
                    checkout_id=checkout_id,
                    reason="Timeout during payment capture. Marked for reconciliation without blind retry.",
                )
                return session

            try:
                capture_resp: PayPalOrderResponse = await self.paypal_client.capture_order(
                    order_id=session.paypal_order_id,
                    request_id=f"{req_id}_cap",
                )
                if capture_resp.status == "COMPLETED":
                    session.state = TransactionState.PAID
                    session.paypal_capture_id = capture_resp.capture_id
                    self.audit_ledger.record_event(
                        event_type="PAYMENT_COMPLETED",
                        checkout_id=checkout_id,
                        policy_version=policy.version,
                        proposal_fingerprint=live_proposal.proposal_fingerprint,
                        reason=f"Payment captured successfully with capture ID {capture_resp.capture_id}",
                    )
                else:
                    session.state = TransactionState.FAILED
                    session.failure_reason = f"PayPal returned status: {capture_resp.status}"
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

        if checkout_id not in self._execution_locks:
            self._execution_locks[checkout_id] = asyncio.Lock()

        async with self._execution_locks[checkout_id]:
            if session.state == TransactionState.PAID:
                return session

            if session.state != TransactionState.AUTHORIZED:
                raise ValueError(f"Cannot execute checkout in state '{session.state}'. Must be AUTHORIZED.")

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

        # Validate order ID matches what we created
        if session.paypal_order_id and session.paypal_order_id != paypal_order_id:
            raise ValueError(
                f"Order ID mismatch: expected '{session.paypal_order_id}', got '{paypal_order_id}'. "
                "Potential tampering detected."
            )

        if checkout_id not in self._execution_locks:
            self._execution_locks[checkout_id] = asyncio.Lock()

        async with self._execution_locks[checkout_id]:
            if session.state == TransactionState.PAID:
                return session

            try:
                capture_resp: PayPalOrderResponse = await self.paypal_client.capture_order(
                    order_id=paypal_order_id,
                    request_id=f"{session.idempotency_key}_cap",
                )
                if capture_resp.status == "COMPLETED":
                    session.state = TransactionState.PAID
                    session.paypal_capture_id = capture_resp.capture_id
                    self.audit_ledger.record_event(
                        event_type="PAYMENT_COMPLETED",
                        checkout_id=checkout_id,
                        reason=f"Live sandbox capture successful. Capture ID: {capture_resp.capture_id}",
                    )
                else:
                    session.state = TransactionState.FAILED
                    session.failure_reason = f"PayPal returned unexpected status: {capture_resp.status}"
            except Exception as e:
                session.state = TransactionState.RECONCILIATION_REQUIRED
                session.failure_reason = f"PayPal capture error: {str(e)}"

            return session

    async def reconcile_timeout(self, checkout_id: str) -> CheckoutSession:
        """Reconcile ambiguous timeout with PayPal."""
        session = self._sessions.get(checkout_id)
        if not session or not session.paypal_order_id:
            raise ValueError(f"Cannot reconcile checkout '{checkout_id}'.")

        details = await self.paypal_client.get_order_details(session.paypal_order_id)
        session.reconciliation_data = details.raw_response

        if details.status == "COMPLETED":
            session.state = TransactionState.PAID
            session.paypal_capture_id = details.capture_id
            self.audit_ledger.record_event(
                event_type="RECONCILIATION_SUCCESS",
                checkout_id=checkout_id,
                reason="Order reconciled as COMPLETED via PayPal lookup.",
            )
        else:
            session.state = TransactionState.FAILED
            session.failure_reason = f"Order reconciled as non-captured ({details.status})."
            self.audit_ledger.record_event(
                event_type="RECONCILIATION_ABORT",
                checkout_id=checkout_id,
                reason=f"Order reconciled as {details.status}. Safe to abort without duplicate charge.",
            )

        return session

    def get_session(self, checkout_id: str) -> Optional[CheckoutSession]:
        return self._sessions.get(checkout_id)
