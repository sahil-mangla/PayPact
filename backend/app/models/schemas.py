from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class PolicyDecisionType(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REJECT = "REJECT"


class TransactionState(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    POLICY_REJECTED = "POLICY_REJECTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    CHECKOUT_CREATED = "CHECKOUT_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


class AgentQuota(BaseModel):
    agent_id: str = Field(..., min_length=1, description="Identifier for this agent persona")
    agent_name: str = Field(..., min_length=1, description="Display name for the agent")
    role: str = Field(..., description="Role of the agent (e.g. Hardware, Travel, Supplies)")
    allocated_budget: float = Field(..., gt=0.0, description="Maximum budget allocated to this agent")
    spent_budget: float = Field(default=0.0, ge=0.0, description="Amount already captured by this agent")
    is_active: bool = Field(default=True, description="Whether this agent is authorized to submit proposals")

    @property
    def remaining_budget(self) -> float:
        return round(max(0.0, self.allocated_budget - self.spent_budget), 2)


class LineItem(BaseModel):
    sku: str = Field(..., min_length=1, description="Unique product SKU or identifier")
    name: str = Field(..., min_length=1, description="Product or service name")
    quantity: int = Field(..., ge=1, description="Purchased quantity, must be >= 1")
    unit_price: float = Field(..., ge=0.0, description="Unit price per item")

    @field_validator("unit_price")
    @classmethod
    def round_unit_price(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("unit_price must be a finite numerical value")
        return round(v, 2)


class AuthorizationPolicy(BaseModel):
    policy_id: str = Field(..., min_length=1, description="Unique authorization policy ID")
    version: int = Field(..., ge=1, description="Policy revision number, starts at 1")
    user_id: str = Field(..., min_length=1, description="User who confirmed this authorization")
    product_category: Optional[str] = Field(None, description="Allowed product category (e.g. mechanical keyboard)")
    maximum_total: float = Field(..., gt=0.0, description="Absolute ceiling budget across line items, tax, and shipping")
    spent_total: float = Field(default=0.0, ge=0.0, description="Cumulative spend across all agents under this policy")
    automatic_purchase_limit: float = Field(
        ..., ge=0.0, description="Maximum amount that can be purchased automatically without explicit approval"
    )
    allowed_currencies: List[str] = Field(default_factory=lambda: ["USD", "INR"])
    allowed_merchants: Optional[List[str]] = Field(None, description="Whitelist of allowed merchants/vendors")
    require_approval_above_limit: bool = Field(
        default=True, description="Whether exceeding automatic_purchase_limit routes to approval instead of reject"
    )
    is_revoked: bool = Field(default=False, description="Whether the user revoked this authorization")
    agent_quotas: dict[str, AgentQuota] = Field(
        default_factory=dict, description="Granular budget quotas assigned per agent persona in swarm"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(None, description="Optional expiry timestamp")

    @field_validator("maximum_total", "automatic_purchase_limit")
    @classmethod
    def round_limits(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Policy limits must be finite numerical values")
        return round(v, 2)

    @field_validator("automatic_purchase_limit")
    @classmethod
    def validate_auto_limit_lte_max(cls, v: float, info) -> float:
        max_total = info.data.get("maximum_total")
        if max_total is not None and v > max_total:
            raise ValueError(f"automatic_purchase_limit ({v}) cannot exceed maximum_total ({max_total})")
        return v


class PurchaseProposal(BaseModel):
    proposal_id: str = Field(..., min_length=1, description="Unique proposal identifier")
    policy_id: str = Field(..., min_length=1, description="ID of policy this proposal is evaluated against")
    policy_version: int = Field(..., ge=1, description="Policy version this proposal was prepared under")
    agent_id: Optional[str] = Field(default="agent_hardware", description="Agent persona that originated this proposal")
    merchant: str = Field(..., min_length=1, description="Merchant or vendor name")
    items: List[LineItem] = Field(..., min_length=1, description="Line items to be purchased")
    item_subtotal: float = Field(..., ge=0.0, description="Sum of line item totals")
    shipping_fee: float = Field(default=0.0, ge=0.0, description="Shipping fee")
    tax_fee: float = Field(default=0.0, ge=0.0, description="Tax amount")
    total_amount: float = Field(..., gt=0.0, description="Calculated final total = subtotal + shipping + tax")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 Currency code")
    proposal_fingerprint: Optional[str] = Field(
        None, description="Canonical SHA-256 fingerprint generated over the proposal data"
    )

    @field_validator("item_subtotal", "shipping_fee", "tax_fee", "total_amount")
    @classmethod
    def round_currency_fields(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Proposal monetary fields must be finite numerical values")
        return round(v, 2)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        clean = v.strip().upper()
        if not clean.isalpha() or len(clean) != 3:
            raise ValueError(f"Currency must be a 3-letter alphabetic code (e.g. USD, INR), got '{v}'")
        return clean


class IntegrityCheckResult(BaseModel):
    check_name: str
    passed: bool
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyEvaluationResult(BaseModel):
    decision: PolicyDecisionType
    policy_id: str
    policy_version: int
    proposal_fingerprint: str
    checks: List[IntegrityCheckResult]
    primary_reason: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalRecord(BaseModel):
    approval_id: str
    proposal_id: str
    proposal_fingerprint: str
    policy_version: int
    approved_by: str
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_valid: bool = True


class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    checkout_id: Optional[str] = None
    policy_version: Optional[int] = None
    proposal_fingerprint: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prev_event_hash: Optional[str] = None
    event_hash: str


class SignedAuditReceipt(BaseModel):
    receipt_id: str
    checkout_id: str
    timestamp: str
    decision: str
    status: str
    agent_id: Optional[str] = None
    policy_id: str
    policy_version: int
    proposal_fingerprint: str
    total_amount: float
    currency: str
    merchant: str
    items_count: int
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    signature_algorithm: str = "HMAC-SHA256"
    signer_identity: str = "APIL-Ledger-Authority-v1"
    signature: str
    raw_canonical_digest: str


class PayPalWebhookEvent(BaseModel):
    id: str
    event_type: str
    create_time: str
    resource_type: Optional[str] = None
    resource: dict[str, Any]
    summary: Optional[str] = None

