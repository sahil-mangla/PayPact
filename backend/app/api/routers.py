from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agent.shopper_agent import ShopperAgent
from app.api.ratelimit import llm_rate_limit, token_rate_limit
from app.catalogue.products import CATALOGUE, Product
from app.lab.benchmark import (
    IntegrityLab,
    SCENARIO_DEFINITIONS,
    ScenarioDefinition,
)
from app.models.schemas import (
    AuthorizationPolicy,
    PolicyRegistration,
    PurchaseProposal,
    SignedAuditReceipt,
)
from app.state.machine import (
    ApprovalLinkError,
    CheckoutNotFoundError,
    CheckoutSession,
    TransactionCoordinator,
)

router = APIRouter(prefix="/api")

def _checkout_error(e: Exception) -> HTTPException:
    """404 for an unknown checkout, 400 for anything the state machine refuses."""
    status = 404 if isinstance(e, CheckoutNotFoundError) else 400
    return HTTPException(status_code=status, detail=str(e))


OWNER_TOKEN_HEADER = "X-Owner-Token"


def _require_owner(
    policy_id: str,
    token: Optional[str],
    action: str,
    checkout_id: Optional[str] = None,
) -> None:
    """Allow only the holder of the policy's owner token: 401 if none was sent, 403 if wrong.

    Every refusal is written to the audit ledger, so a self-approving agent leaves a trace.
    """
    if token is None or not token.strip():
        coordinator.record_approval_denied(
            f"{action.capitalize()} refused: no owner token was presented.",
            action,
            checkout_id=checkout_id,
            policy_id=policy_id,
        )
        raise HTTPException(
            status_code=401, detail=f"Owner token required (send the {OWNER_TOKEN_HEADER} header)."
        )
    if not coordinator.verify_owner_token(policy_id, token):
        coordinator.record_approval_denied(
            f"{action.capitalize()} refused: the owner token did not match this policy.",
            action,
            checkout_id=checkout_id,
            policy_id=policy_id,
        )
        raise HTTPException(status_code=403, detail="Invalid owner token for this policy.")


# Global singleton coordinator & lab for the app
coordinator = TransactionCoordinator()
lab = IntegrityLab()


class ParseIntentRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="Natural language purchase request",
    )
    user_id: str = Field(
        default="usr_shopper", max_length=64, description="User identifier"
    )


class CreateProposalRequest(BaseModel):
    prompt: str = Field(..., min_length=2, max_length=500)
    policy_id: str = Field(..., min_length=1, max_length=64)
    preferred_sku: Optional[str] = Field(None, max_length=64)
    agent_id: Optional[str] = Field(
        default="agent_hardware",
        max_length=64,
        description="Agent persona ID in swarm",
    )


class SimulateWebhookRequest(BaseModel):
    checkout_id: str
    event_type: str = Field(
        default="PAYMENT.CAPTURE.REFUNDED",
        description="PayPal event type (e.g. PAYMENT.CAPTURE.REFUNDED, CUSTOMER.DISPUTE.CREATED)",
    )
    amount: Optional[float] = Field(None, gt=0)
    reason: Optional[str] = None


class ApproveProposalRequest(BaseModel):
    user_id: str = Field(default="usr_shopper")


class ExecutePaymentRequest(BaseModel):
    simulate_drift_type: Optional[Literal["price_drift", "sku_substitution", "timeout"]] = Field(
        None,
        description="Optional simulation: 'price_drift', 'sku_substitution', 'timeout'",
    )
    drift_shipping_fee: Optional[float] = Field(None, ge=0, le=1_000_000)
    drift_sku: Optional[str] = Field(None, max_length=64)


class CapturePaymentRequest(BaseModel):
    """Request to capture an already-approved PayPal order (used with PayPal JS SDK flow)."""

    paypal_order_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9-]{1,64}$",
        description="The PayPal Order ID to capture (returned by createOrder callback)",
    )


class LabRunRequest(BaseModel):
    scenario_id: Optional[str] = Field(None, max_length=16)
    system_type: Literal["BASELINE_A", "BASELINE_B", "PROPOSED_APIL"] = "PROPOSED_APIL"


# ----------------------------------------------------
# 1. Health & Catalogue
# ----------------------------------------------------
# Probing Ollama and Gemini costs a network round trip each, and /health doubles as the
# hosting platform's liveness check, so the model status is cached briefly.
_MODEL_HEALTH_TTL_SECONDS = 30.0
_model_health_cache: Dict[str, Any] = {}


def reset_model_health_cache() -> None:
    _model_health_cache.clear()


def _public_model_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Availability and model name only: no URLs, error bodies or installed-model lists."""
    return {k: info[k] for k in ("available", "model", "installed", "provider") if k in info}


def _model_health() -> Dict[str, Any]:
    cached = _model_health_cache.get("value")
    now = time.monotonic()
    if cached and now - cached[0] < _MODEL_HEALTH_TTL_SECONDS:
        return cached[1]
    from app.agent.gemini_client import GeminiClient
    from app.agent.ollama_client import OllamaClient

    value = {
        "ollama": _public_model_info(OllamaClient.check_health()),
        "gemini": _public_model_info(GeminiClient.check_health()),
    }
    _model_health_cache["value"] = (now, value)
    return value


@router.get("/health")
async def health_check():
    is_mock = coordinator.paypal_client.mock_mode
    models = await run_in_threadpool(_model_health)
    return {
        "status": "healthy",
        "service": "Agent Payment Integrity Layer (APIL)",
        "paypal_mode": "mock" if is_mock else "live_sandbox",
        **models,
    }


@router.get("/agent/model-status")
async def get_agent_model_status():
    """Return local Ollama AI model availability and active configuration."""
    return (await run_in_threadpool(_model_health))["ollama"]


@router.get("/catalogue", response_model=List[Product])
async def get_catalogue():
    return CATALOGUE


# ----------------------------------------------------
# 2. Authorization Policies
# ----------------------------------------------------
@router.post(
    "/authorizations/parse-intent",
    response_model=AuthorizationPolicy,
    dependencies=[Depends(llm_rate_limit)],
)
async def parse_intent_to_policy(req: ParseIntentRequest):
    """Extract structured policy constraints from natural language."""
    # The agent calls an LLM over blocking HTTP; keep that off the event loop.
    return await run_in_threadpool(
        ShopperAgent.parse_intent_to_policy, req.prompt, user_id=req.user_id
    )


@router.post("/authorizations", response_model=PolicyRegistration)
async def register_policy(policy: AuthorizationPolicy):
    """Register user-confirmed authorization policy.

    The response carries the owner token once. Only its hash is kept, so a lost token cannot be
    recovered; the owner is the only party who ever sees it, never the agent.

    Spend and revocation state belong to the server, so anything the client sends for them is
    reset, and an existing policy id can never be replaced (that would undo a revocation).
    """
    if coordinator.get_policy(policy.policy_id):
        raise HTTPException(
            status_code=409, detail=f"Policy '{policy.policy_id}' already exists."
        )
    policy.spent_total = 0.0
    policy.is_revoked = False
    for quota in policy.agent_quotas.values():
        quota.spent_budget = 0.0
    registered = coordinator.register_policy(policy)
    token = coordinator.issue_owner_token(registered.policy_id)
    return PolicyRegistration(**registered.model_dump(), owner_token=token)


@router.get("/authorizations/{policy_id}", response_model=AuthorizationPolicy)
async def get_policy(policy_id: str):
    policy = coordinator.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return policy


@router.get(
    "/authorizations/{policy_id}/checkouts", dependencies=[Depends(token_rate_limit)]
)
async def list_policy_checkouts(
    policy_id: str,
    x_owner_token: Optional[str] = Header(None, alias=OWNER_TOKEN_HEADER),
):
    """The checkouts opened under this policy (by the web agent or an MCP agent), newest first.

    Owner-only: this is how the owner finds a request that is waiting for their approval.
    """
    if not coordinator.get_policy(policy_id):
        raise HTTPException(status_code=404, detail="Policy not found.")
    _require_owner(policy_id, x_owner_token, "list-checkouts")
    return coordinator.list_policy_checkouts(policy_id)


@router.post(
    "/authorizations/{policy_id}/revoke", dependencies=[Depends(token_rate_limit)]
)
async def revoke_policy(
    policy_id: str,
    x_owner_token: Optional[str] = Header(None, alias=OWNER_TOKEN_HEADER),
):
    if not coordinator.get_policy(policy_id):
        raise HTTPException(status_code=404, detail="Policy not found.")
    _require_owner(policy_id, x_owner_token, "revoke")
    success = coordinator.revoke_policy(policy_id)
    if not success:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return {"status": "revoked", "policy_id": policy_id}


# ----------------------------------------------------
# 3. Agent Proposals & Checkout Lifecycle
# ----------------------------------------------------
async def run_proposal(
    prompt: str,
    policy_id: str,
    preferred_sku: Optional[str] = None,
    agent_id: Optional[str] = "agent_hardware",
) -> Dict[str, Any]:
    """Have the shopper agent propose a purchase and open a checkout session for it.

    Shared by POST /api/proposals and the MCP propose_purchase tool, so both go through the
    same agent and the same policy gate. Raises HTTPException (404 unknown policy, 400 agent error).
    """
    policy = coordinator.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")

    try:
        agent_res = await run_in_threadpool(
            ShopperAgent.generate_proposal,
            user_prompt=prompt,
            policy=policy,
            preferred_sku=preferred_sku,
            agent_id=agent_id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    proposal: PurchaseProposal = agent_res["proposal"]
    session = coordinator.create_proposal_session(proposal, policy)

    return {
        "checkout_id": session.checkout_id,
        "state": session.state.value,
        "recommendation_explanation": agent_res["recommendation_explanation"],
        "proposal": proposal,
        "product": agent_res["product"],
        "agent_mode": agent_res.get("agent_mode", "deterministic"),
        "agent_trace": agent_res.get("agent_trace", []),
        "failure_reason": session.failure_reason,
    }


@router.post("/proposals", dependencies=[Depends(llm_rate_limit)])
async def create_proposal(req: CreateProposalRequest):
    return await run_proposal(
        req.prompt, req.policy_id, preferred_sku=req.preferred_sku, agent_id=req.agent_id
    )


@router.post(
    "/checkouts/{checkout_id}/approve",
    response_model=CheckoutSession,
    dependencies=[Depends(token_rate_limit)],
)
async def approve_checkout(
    checkout_id: str,
    req: ApproveProposalRequest,
    x_owner_token: Optional[str] = Header(None, alias=OWNER_TOKEN_HEADER),
):
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Checkout '{checkout_id}' not found.")
    _require_owner(session.policy_id, x_owner_token, "approve", checkout_id=checkout_id)
    try:
        return coordinator.approve_proposal(checkout_id, user_id=req.user_id)
    except Exception as e:
        raise _checkout_error(e)


@router.post(
    "/checkouts/{checkout_id}/approval-link", dependencies=[Depends(token_rate_limit)]
)
async def create_approval_link(
    checkout_id: str,
    x_owner_token: Optional[str] = Header(None, alias=OWNER_TOKEN_HEADER),
):
    """Mint a one-time link (30 minutes, bound to this exact proposal) the owner can open to approve."""
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Checkout '{checkout_id}' not found.")
    _require_owner(session.policy_id, x_owner_token, "approval-link", checkout_id=checkout_id)
    try:
        token, expires_at = coordinator.mint_approval_link(checkout_id)
    except Exception as e:
        raise _checkout_error(e)
    # FRONTEND_URL is what render.yaml sets (and what the PayPal return URLs use), so fall back to it.
    base = (
        os.getenv("FRONTEND_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000"
    ).strip().rstrip("/")
    return {"approval_url": f"{base}/approve/{token}", "expires_at": expires_at}


@router.get("/approvals/{token}", dependencies=[Depends(token_rate_limit)])
async def get_approval_summary(token: str):
    """Human-readable summary of what a link would approve. Does not use up the link."""
    try:
        return coordinator.get_approval_summary(token)
    except ApprovalLinkError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post(
    "/approvals/{token}",
    response_model=CheckoutSession,
    dependencies=[Depends(token_rate_limit)],
)
async def redeem_approval_link(token: str):
    """Approve the checkout the link was minted for. Works once."""
    try:
        return coordinator.redeem_approval_link(token)
    except ApprovalLinkError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise _checkout_error(e)


async def run_execute(checkout_id: str, req: ExecutePaymentRequest) -> Dict[str, Any]:
    """
    Execute step 1: Runs pre-execution invariant gate, creates PayPal order.

    In LIVE SANDBOX mode: returns the PayPal approve URL for the JS SDK to open.
    In MOCK mode: creates + captures inline and returns PAID state.

    For drift/rejection scenarios, blocks immediately without creating an order.
    """
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Checkout '{checkout_id}' not found."
        )

    # Prepare live proposal if drift simulation requested
    live_proposal = session.proposal.model_copy(deep=True)
    if req.simulate_drift_type == "price_drift":
        shipping = (
            req.drift_shipping_fee if req.drift_shipping_fee is not None else 850.00
        )
        live_proposal.shipping_fee = shipping
        live_proposal.total_amount = round(
            live_proposal.item_subtotal + shipping + live_proposal.tax_fee, 2
        )
    elif req.simulate_drift_type == "sku_substitution":
        sub_sku = req.drift_sku or "KB-SUBSTITUTED-CHEAP"
        if live_proposal.items:
            live_proposal.items[0].sku = sub_sku
            live_proposal.items[0].name = "Substituted SKU"

    sim_timeout = req.simulate_drift_type == "timeout"

    is_mock = coordinator.paypal_client.mock_mode

    try:
        if is_mock:
            # Mock mode: full inline create + capture (original behavior)
            updated_session = await coordinator.execute_payment(
                checkout_id=checkout_id,
                current_proposal_state=live_proposal
                if req.simulate_drift_type
                else None,
                simulate_timeout=sim_timeout,
            )
            return {
                "session": updated_session,
                "paypal_mode": "mock",
                "needs_buyer_approval": False,
                "approve_url": None,
            }
        else:
            # Live sandbox: run policy gate + create order only, return approve URL
            updated_session = await coordinator.create_paypal_order_only(
                checkout_id=checkout_id,
                current_proposal_state=live_proposal
                if req.simulate_drift_type
                else None,
                simulate_timeout=sim_timeout,
            )

            # If blocked by policy, return immediately
            if updated_session.state.value in ("POLICY_REJECTED", "FAILED"):
                return {
                    "session": updated_session,
                    "paypal_mode": "live_sandbox",
                    "needs_buyer_approval": False,
                    "approve_url": None,
                }

            # Find the approve URL from the PayPal order
            approve_url = None
            if updated_session.paypal_order_id:
                # PayPal JS SDK flow: use orderID directly, no redirect needed
                approve_url = f"https://www.sandbox.paypal.com/checkoutnow?token={updated_session.paypal_order_id}"

            return {
                "session": updated_session,
                "paypal_mode": "live_sandbox",
                "needs_buyer_approval": True,
                "paypal_order_id": updated_session.paypal_order_id,
                "approve_url": approve_url,
            }
    except Exception as e:
        raise _checkout_error(e)


@router.post("/checkouts/{checkout_id}/execute")
async def execute_checkout(checkout_id: str, req: ExecutePaymentRequest):
    return await run_execute(checkout_id, req)


@router.post("/checkouts/{checkout_id}/capture")
async def capture_checkout(checkout_id: str, req: CapturePaymentRequest):
    """
    Execute step 2 (live sandbox only): Called by PayPal JS SDK onApprove callback.
    Captures the PayPal order after the buyer has approved it in the PayPal popup.
    """
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Checkout '{checkout_id}' not found."
        )

    try:
        updated_session = await coordinator.capture_approved_order(
            checkout_id=checkout_id,
            paypal_order_id=req.paypal_order_id,
        )
        return {"session": updated_session, "paypal_mode": "live_sandbox"}
    except Exception as e:
        raise _checkout_error(e)


@router.post("/checkouts/{checkout_id}/reconcile", response_model=CheckoutSession)
async def reconcile_checkout(checkout_id: str):
    try:
        return await coordinator.reconcile_timeout(checkout_id)
    except Exception as e:
        raise _checkout_error(e)


@router.get("/checkouts/{checkout_id}", response_model=CheckoutSession)
async def get_checkout(checkout_id: str):
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Checkout not found.")
    return session


@router.get("/checkouts/{checkout_id}/receipt")
async def get_checkout_receipt(checkout_id: str):
    """Generate tamper-evident, digitally signed audit receipt for a checkout session."""
    try:
        return coordinator.generate_audit_receipt(checkout_id)
    except Exception as e:
        raise _checkout_error(e)


@router.get("/receipt/sample")
async def get_sample_receipt():
    """Return an authentic cryptographically signed sample receipt for verifier testing."""
    from app.crypto.receipts import generate_signed_receipt

    return generate_signed_receipt(
        checkout_id="chk_demo_sample_receipt",
        decision="ALLOW",
        status="PAID",
        policy_id="pol_demo_standard",
        policy_version=1,
        proposal_fingerprint="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        total_amount=3899.00,
        currency="INR",
        merchant="Keychron India Official",
        items_count=1,
        agent_id="agent_hardware",
        paypal_order_id="5A123456789012345",
        paypal_capture_id="CAP_9876543210987",
    )


@router.post("/receipt/verify")
async def verify_receipt_endpoint(receipt: SignedAuditReceipt):
    """Verify cryptographic authenticity and tamper-resistance of a SignedAuditReceipt."""
    from app.crypto.receipts import verify_signed_receipt

    is_valid = verify_signed_receipt(receipt)
    return {
        "valid": is_valid,
        "receipt_id": receipt.receipt_id,
        "checkout_id": receipt.checkout_id,
        "algorithm": receipt.signature_algorithm,
        "signer": receipt.signer_identity,
    }


@router.post("/webhooks/paypal")
async def handle_paypal_webhook(request: Request):
    """Production PayPal Webhook Listener endpoint.

    Every delivery is verified against PayPal's signature API before it can touch
    checkout state. With no PAYPAL_WEBHOOK_ID configured, or in mock mode, it is
    rejected: use /webhooks/simulate for local demos.
    """
    webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
    if coordinator.paypal_client.mock_mode or not webhook_id:
        raise HTTPException(
            status_code=503,
            detail="PayPal webhook verification is not configured (set PAYPAL_WEBHOOK_ID with live sandbox credentials).",
        )
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Webhook body must be JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be an object.")

    verified = await coordinator.paypal_client.verify_webhook_signature(
        headers=request.headers, event=payload, webhook_id=webhook_id
    )
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid PayPal webhook signature.")

    event_type = payload.get("event_type", "")
    resource = payload.get("resource", {})
    summary = payload.get("summary")
    session = await coordinator.process_webhook_event(
        event_type=event_type,
        resource=resource,
        summary=summary,
        event_id=payload.get("id"),
    )
    return {
        "status": "processed",
        "event_type": event_type,
        "updated_checkout": session.checkout_id if session else None,
    }


@router.post("/webhooks/simulate")
async def simulate_paypal_webhook(req: SimulateWebhookRequest):
    """Interactive webhook simulation for local demos and Integrity Lab.

    It fabricates PayPal events, so it only runs in mock mode unless explicitly enabled.
    """
    if not (
        coordinator.paypal_client.mock_mode
        or os.getenv("ENABLE_WEBHOOK_SIMULATION", "").lower() in ("true", "1", "yes")
    ):
        raise HTTPException(
            status_code=403,
            detail="Webhook simulation is disabled against live PayPal (set ENABLE_WEBHOOK_SIMULATION=true for a demo).",
        )
    session = coordinator.get_session(req.checkout_id)
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Checkout '{req.checkout_id}' not found."
        )

    refund_amount = req.amount or session.proposal.total_amount
    simulated_resource = {
        "id": session.paypal_capture_id or f"SIM-CAP-{req.checkout_id}",
        "amount": {
            "value": f"{refund_amount:.2f}",
            "currency_code": session.proposal.currency,
        },
    }
    updated = await coordinator.process_webhook_event(
        event_type=req.event_type,
        resource=simulated_resource,
        checkout_id=req.checkout_id,
        summary=req.reason or f"Simulated {req.event_type} event",
    )
    return {"status": "simulated", "session": updated}


@router.get("/swarm/personas")
async def get_swarm_personas():
    """List available specialized agent personas in the swarm with quota defaults."""
    return [
        {
            "agent_id": "agent_hardware",
            "name": "Hardware Procurement Agent",
            "role": "Hardware & Tech Accessories",
            "quota_pct": 60,
            "description": "Autonomous agent for sourcing computer peripherals, keycaps, and hardware components.",
        },
        {
            "agent_id": "agent_travel",
            "name": "Travel & Bookings Agent",
            "role": "Flights, Hotels & Transit",
            "quota_pct": 25,
            "description": "Agent for booking corporate flights, hotel accommodations, and conference passes.",
        },
        {
            "agent_id": "agent_supplies",
            "name": "Office Supplies Agent",
            "role": "Desk Accessories & Peripherals",
            "quota_pct": 15,
            "description": "Agent for recurring workplace supplies, cables, and ergonomic accessories.",
        },
    ]


# ----------------------------------------------------
# 4. Audit Trail
# ----------------------------------------------------
@router.get("/audit/events")
async def get_audit_events(checkout_id: Optional[str] = Query(None)):
    events = coordinator.audit_ledger.get_events(checkout_id=checkout_id)
    is_valid = coordinator.audit_ledger.verify_ledger_integrity()
    return {
        "ledger_integrity_valid": is_valid,
        "event_count": len(events),
        "events": events,
    }


# ----------------------------------------------------
# 5. Integrity Lab Benchmark API
# ----------------------------------------------------
@router.get("/lab/scenarios", response_model=List[ScenarioDefinition])
async def list_scenarios():
    return SCENARIO_DEFINITIONS


@router.post("/lab/run")
async def run_lab_test(req: LabRunRequest):
    if req.scenario_id:
        if req.scenario_id not in {d.scenario_id for d in SCENARIO_DEFINITIONS}:
            raise HTTPException(
                status_code=404, detail=f"Unknown scenario '{req.scenario_id}'."
            )
        result = await lab.run_scenario(req.scenario_id, system_type=req.system_type)
        return {"single_run": result}
    else:
        report = await lab.run_full_benchmark()
        return {"benchmark_report": report}
