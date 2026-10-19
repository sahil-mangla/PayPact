from app.fingerprint.canonical import (
    compute_proposal_fingerprint,
    get_fingerprint_diff,
    verify_proposal_fingerprint,
)
from app.models.schemas import LineItem, PurchaseProposal


def make_sample_proposal(
    price: float = 3899.00,
    shipping: float = 0.00,
    tax: float = 0.00,
    sku: str = "KB-K2-V2-RGB",
    merchant: str = "Keychron India",
    version: int = 1,
) -> PurchaseProposal:
    item = LineItem(
        sku=sku,
        name="Keychron K2 Wireless Mechanical Keyboard",
        quantity=1,
        unit_price=price,
    )
    total = round(price + shipping + tax, 2)
    return PurchaseProposal(
        proposal_id="prop_test_01",
        policy_id="pol_test_01",
        policy_version=version,
        merchant=merchant,
        items=[item],
        item_subtotal=price,
        shipping_fee=shipping,
        tax_fee=tax,
        total_amount=total,
        currency="INR",
    )


def test_fingerprint_deterministic_and_reproducible():
    p1 = make_sample_proposal()
    p2 = make_sample_proposal()
    
    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    
    assert fp1 == fp2
    assert len(fp1) == 64
    assert verify_proposal_fingerprint(p1, fp1) is True


def test_fingerprint_changes_on_price_drift():
    p1 = make_sample_proposal(price=3899.00)
    p2 = make_sample_proposal(price=3900.00)  # Drift of just 1 rupee
    
    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    
    assert fp1 != fp2
    assert verify_proposal_fingerprint(p1, fp2) is False
    
    diff = get_fingerprint_diff(p1, p2)
    assert "total_amount" in diff
    assert diff["total_amount"]["original"] == "3899.00"
    assert diff["total_amount"]["current"] == "3900.00"


def test_fingerprint_changes_on_added_shipping_fee():
    p1 = make_sample_proposal(shipping=0.00)
    p2 = make_sample_proposal(shipping=150.00)
    
    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    
    assert fp1 != fp2
    diff = get_fingerprint_diff(p1, p2)
    assert "shipping_fee" in diff
    assert diff["shipping_fee"]["original"] == "0.00"
    assert diff["shipping_fee"]["current"] == "150.00"


def test_fingerprint_changes_on_product_substitution():
    p1 = make_sample_proposal(sku="KB-K2-V2-RGB")
    p2 = make_sample_proposal(sku="KB-K2-V2-WHITE")  # Substituted switch/variant
    
    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    
    assert fp1 != fp2


def test_fingerprint_item_order_independence():
    """Ensure that line item order does not change canonical fingerprint (sorted by SKU)."""
    item_a = LineItem(sku="SKU-A", name="Item A", quantity=1, unit_price=10.00)
    item_b = LineItem(sku="SKU-B", name="Item B", quantity=1, unit_price=20.00)

    p1 = PurchaseProposal(
        proposal_id="p1",
        policy_id="pol1",
        policy_version=1,
        merchant="Store",
        items=[item_a, item_b],
        item_subtotal=30.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=30.00,
        currency="USD",
    )

    p2 = PurchaseProposal(
        proposal_id="p2",
        policy_id="pol1",
        policy_version=1,
        merchant="Store",
        items=[item_b, item_a],  # Reverse order
        item_subtotal=30.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=30.00,
        currency="USD",
    )

    fp1 = compute_proposal_fingerprint(p1)
    fp2 = compute_proposal_fingerprint(p2)
    assert fp1 == fp2
