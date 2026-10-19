import hashlib
import hmac
import json
from typing import Any, Dict, List
from app.models.schemas import LineItem, PurchaseProposal


def normalize_items_for_fingerprint(items: List[LineItem]) -> List[Dict[str, Any]]:
    """Normalize line items: sort by SKU, format unit_price as 2-decimal string."""
    normalized = []
    # Multi-key sorting guarantees 100% deterministic order even with duplicate SKUs
    for item in sorted(
        items,
        key=lambda x: (x.sku.strip(), f"{x.unit_price:.2f}", x.name.strip(), x.quantity),
    ):
        normalized.append({
            "sku": item.sku.strip(),
            "name": item.name.strip(),
            "quantity": item.quantity,
            "unit_price": f"{item.unit_price:.2f}",
        })
    return normalized


def normalize_proposal_for_fingerprint(proposal: PurchaseProposal) -> Dict[str, Any]:
    """Produce a canonical normalized dictionary representation of a proposal.
    
    Any variation in merchant, currency, line items, taxes, or total will alter
    this dictionary and thus change the resulting SHA-256 fingerprint.
    """
    return {
        "policy_id": proposal.policy_id.strip(),
        "policy_version": proposal.policy_version,
        "merchant": proposal.merchant.strip().lower(),
        "items": normalize_items_for_fingerprint(proposal.items),
        "item_subtotal": f"{proposal.item_subtotal:.2f}",
        "shipping_fee": f"{proposal.shipping_fee:.2f}",
        "tax_fee": f"{proposal.tax_fee:.2f}",
        "total_amount": f"{proposal.total_amount:.2f}",
        "currency": proposal.currency.strip().upper(),
    }


def compute_proposal_fingerprint(proposal: PurchaseProposal) -> str:
    """Compute deterministic SHA-256 hex digest of the canonical proposal representation."""
    canonical_dict = normalize_proposal_for_fingerprint(proposal)
    # Serialize strictly with sorted keys and compact separators
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_proposal_fingerprint(proposal: PurchaseProposal, expected_fingerprint: str) -> bool:
    """Verify whether a proposal matches an expected canonical fingerprint (constant-time)."""
    if not expected_fingerprint:
        return False
    actual = compute_proposal_fingerprint(proposal)
    return hmac.compare_digest(actual.lower(), expected_fingerprint.strip().lower())


def get_fingerprint_diff(p1: PurchaseProposal, p2: PurchaseProposal) -> Dict[str, Any]:
    """Compare two proposals and identify exact fields that drifted."""
    d1 = normalize_proposal_for_fingerprint(p1)
    d2 = normalize_proposal_for_fingerprint(p2)
    diff: Dict[str, Any] = {}
    for key in d1:
        if d1[key] != d2.get(key):
            diff[key] = {
                "original": d1[key],
                "current": d2.get(key),
            }
    return diff
