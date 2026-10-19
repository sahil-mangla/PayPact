from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent.shopper_agent import ShopperAgent
from app.catalogue.products import CATALOGUE, Product, get_product_by_sku
from app.lab.benchmark import (
    BenchmarkReport,
    IntegrityLab,
    SCENARIO_DEFINITIONS,
    ScenarioDefinition,
    ScenarioRunResult,
)
from app.models.schemas import (
    AuditEvent,
    AuthorizationPolicy,
    PolicyEvaluationResult,
    PurchaseProposal,
)
from app.state.machine import CheckoutSession, TransactionCoordinator

router = APIRouter(prefix="/api")

# Global singleton coordinator & lab for the app
coordinator = TransactionCoordinator()
lab = IntegrityLab()


class ParseIntentRequest(BaseModel):
    prompt: str = Field(..., min_length=2, description="Natural language purchase request")
    user_id: str = Field(default="usr_shopper", description="User identifier")


class CreateProposalRequest(BaseModel):
    prompt: str = Field(..., min_length=2)
    policy_id: str = Field(..., min_length=1)
    preferred_sku: Optional[str] = None


class ApproveProposalRequest(BaseModel):
    user_id: str = Field(default="usr_shopper")


class ExecutePaymentRequest(BaseModel):
    simulate_drift_type: Optional[str] = Field(
        None, description="Optional simulation: 'price_drift', 'sku_substitution', 'timeout'"
    )
    drift_shipping_fee: Optional[float] = None
    drift_sku: Optional[str] = None


class LabRunRequest(BaseModel):
    scenario_id: Optional[str] = None
    system_type: str = Field(default="PROPOSED_APIL")  # BASELINE_A, BASELINE_B, PROPOSED_APIL


# ----------------------------------------------------
# 1. Health & Catalogue
# ----------------------------------------------------
@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Agent Payment Integrity Layer (APIL)",
        "paypal_mode": "mock" if coordinator.paypal_client.mock_mode else "live_sandbox",
    }


@router.get("/catalogue", response_model=List[Product])
async def get_catalogue():
    return CATALOGUE


# ----------------------------------------------------
# 2. Authorization Policies
# ----------------------------------------------------
@router.post("/authorizations/parse-intent", response_model=AuthorizationPolicy)
async def parse_intent_to_policy(req: ParseIntentRequest):
    """Extract structured policy constraints from natural language."""
    return ShopperAgent.parse_intent_to_policy(req.prompt, user_id=req.user_id)


@router.post("/authorizations", response_model=AuthorizationPolicy)
async def register_policy(policy: AuthorizationPolicy):
    """Register user-confirmed authorization policy."""
    return coordinator.register_policy(policy)


@router.get("/authorizations/{policy_id}", response_model=AuthorizationPolicy)
async def get_policy(policy_id: str):
    policy = coordinator.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return policy


@router.post("/authorizations/{policy_id}/revoke")
async def revoke_policy(policy_id: str):
    success = coordinator.revoke_policy(policy_id)
    if not success:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return {"status": "revoked", "policy_id": policy_id}


# ----------------------------------------------------
# 3. Agent Proposals & Checkout Lifecycle
# ----------------------------------------------------
@router.post("/proposals")
async def create_proposal(req: CreateProposalRequest):
    policy = coordinator.get_policy(req.policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy '{req.policy_id}' not found.")

    try:
        agent_res = ShopperAgent.generate_proposal(
            user_prompt=req.prompt,
            policy=policy,
            preferred_sku=req.preferred_sku,
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
        "failure_reason": session.failure_reason,
    }


@router.post("/checkouts/{checkout_id}/approve", response_model=CheckoutSession)
async def approve_checkout(checkout_id: str, req: ApproveProposalRequest):
    try:
        return coordinator.approve_proposal(checkout_id, user_id=req.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/checkouts/{checkout_id}/execute", response_model=CheckoutSession)
async def execute_checkout(checkout_id: str, req: ExecutePaymentRequest):
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Checkout '{checkout_id}' not found.")

    # Prepare live proposal if drift simulation requested
    live_proposal = session.proposal.model_copy(deep=True)
    if req.simulate_drift_type == "price_drift":
        shipping = req.drift_shipping_fee if req.drift_shipping_fee is not None else 850.00
        live_proposal.shipping_fee = shipping
        live_proposal.total_amount = round(live_proposal.item_subtotal + shipping + live_proposal.tax_fee, 2)
    elif req.simulate_drift_type == "sku_substitution":
        sub_sku = req.drift_sku or "KB-SUBSTITUTED-CHEAP"
        live_proposal.items[0].sku = sub_sku
        live_proposal.items[0].name = "Substituted SKU"

    sim_timeout = (req.simulate_drift_type == "timeout")

    try:
        updated_session = await coordinator.execute_payment(
            checkout_id=checkout_id,
            current_proposal_state=live_proposal if req.simulate_drift_type else None,
            simulate_timeout=sim_timeout,
        )
        return updated_session
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/checkouts/{checkout_id}/reconcile", response_model=CheckoutSession)
async def reconcile_checkout(checkout_id: str):
    try:
        return await coordinator.reconcile_timeout(checkout_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/checkouts/{checkout_id}", response_model=CheckoutSession)
async def get_checkout(checkout_id: str):
    session = coordinator.get_session(checkout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Checkout not found.")
    return session


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
        result = await lab.run_scenario(req.scenario_id, system_type=req.system_type)
        return {"single_run": result}
    else:
        report = await lab.run_full_benchmark()
        return {"benchmark_report": report}
