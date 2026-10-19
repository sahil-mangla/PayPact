"""Cryptographic Receipt Generator & Verifier for APIL.

Generates tamper-evident, digitally signed audit receipts (HMAC-SHA256 / JSON-LD)
that bind the approved cryptographic proposal fingerprint, policy constraints,
and PayPal execution telemetry together for external dispute defense.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.models.schemas import SignedAuditReceipt


APIL_SIGNING_SECRET = os.getenv("APIL_SIGNING_SECRET", "apil_master_cryptographic_audit_signing_secret_2026")
SIGNER_IDENTITY = "APIL-Ledger-Authority-v1.0"


def generate_signed_receipt(
    checkout_id: str,
    decision: str,
    status: str,
    policy_id: str,
    policy_version: int,
    proposal_fingerprint: str,
    total_amount: float,
    currency: str,
    merchant: str,
    items_count: int,
    agent_id: Optional[str] = None,
    paypal_order_id: Optional[str] = None,
    paypal_capture_id: Optional[str] = None,
    signing_secret: Optional[str] = None,
) -> SignedAuditReceipt:
    """Generate and cryptographically sign a verifiable audit receipt."""
    receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    secret = (signing_secret or APIL_SIGNING_SECRET).encode("utf-8")

    # Canonical dictionary of core fields to bind
    core_payload = {
        "receipt_id": receipt_id,
        "checkout_id": checkout_id,
        "timestamp": timestamp,
        "decision": decision,
        "status": status,
        "agent_id": agent_id or "agent_hardware",
        "policy_id": policy_id,
        "policy_version": policy_version,
        "proposal_fingerprint": proposal_fingerprint,
        "total_amount": f"{total_amount:.2f}",
        "currency": currency.upper(),
        "merchant": merchant.strip(),
        "items_count": items_count,
        "paypal_order_id": paypal_order_id or "NONE",
        "paypal_capture_id": paypal_capture_id or "NONE",
        "signer_identity": SIGNER_IDENTITY,
    }

    canonical_json = json.dumps(core_payload, sort_keys=True, separators=(",", ":"))
    raw_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    signature = hmac.new(secret, canonical_json.encode("utf-8"), hashlib.sha256).hexdigest()

    return SignedAuditReceipt(
        receipt_id=receipt_id,
        checkout_id=checkout_id,
        timestamp=timestamp,
        decision=decision,
        status=status,
        agent_id=agent_id,
        policy_id=policy_id,
        policy_version=policy_version,
        proposal_fingerprint=proposal_fingerprint,
        total_amount=round(total_amount, 2),
        currency=currency.upper(),
        merchant=merchant.strip(),
        items_count=items_count,
        paypal_order_id=paypal_order_id,
        paypal_capture_id=paypal_capture_id,
        signature_algorithm="HMAC-SHA256",
        signer_identity=SIGNER_IDENTITY,
        signature=signature,
        raw_canonical_digest=raw_digest,
    )


def verify_signed_receipt(
    receipt: SignedAuditReceipt,
    signing_secret: Optional[str] = None,
) -> bool:
    """Verify cryptographic authenticity and tamper-resistance of a SignedAuditReceipt."""
    secret = (signing_secret or APIL_SIGNING_SECRET).encode("utf-8")

    core_payload = {
        "receipt_id": receipt.receipt_id,
        "checkout_id": receipt.checkout_id,
        "timestamp": receipt.timestamp,
        "decision": receipt.decision,
        "status": receipt.status,
        "agent_id": receipt.agent_id or "agent_hardware",
        "policy_id": receipt.policy_id,
        "policy_version": receipt.policy_version,
        "proposal_fingerprint": receipt.proposal_fingerprint,
        "total_amount": f"{receipt.total_amount:.2f}",
        "currency": receipt.currency.upper(),
        "merchant": receipt.merchant.strip(),
        "items_count": receipt.items_count,
        "paypal_order_id": receipt.paypal_order_id or "NONE",
        "paypal_capture_id": receipt.paypal_capture_id or "NONE",
        "signer_identity": receipt.signer_identity,
    }

    canonical_json = json.dumps(core_payload, sort_keys=True, separators=(",", ":"))
    expected_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    expected_signature = hmac.new(secret, canonical_json.encode("utf-8"), hashlib.sha256).hexdigest()

    # Constant-time comparison to prevent timing attacks
    sig_valid = hmac.compare_digest(receipt.signature, expected_signature)
    digest_valid = hmac.compare_digest(receipt.raw_canonical_digest, expected_digest)

    return sig_valid and digest_valid
