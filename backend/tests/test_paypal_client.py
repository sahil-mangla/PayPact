import pytest
from app.models.schemas import LineItem, PurchaseProposal
from app.payments.paypal_client import PayPalClient


@pytest.fixture
def mock_paypal_client():
    return PayPalClient(mock_mode=True)


@pytest.fixture
def sample_proposal():
    item = LineItem(
        sku="KB-K2-V2-RGB",
        name="Keychron K2 Keyboard",
        quantity=1,
        unit_price=3899.00,
    )
    return PurchaseProposal(
        proposal_id="prop_pay_01",
        policy_id="pol_01",
        policy_version=1,
        merchant="Keychron India",
        items=[item],
        item_subtotal=3899.00,
        shipping_fee=0.00,
        tax_fee=0.00,
        total_amount=3899.00,
        currency="INR",
        proposal_fingerprint="mock_fp_abc123",
    )


@pytest.mark.asyncio
async def test_create_order_mock(mock_paypal_client, sample_proposal):
    order = await mock_paypal_client.create_order(sample_proposal, request_id="req_001")
    assert order.order_id.startswith("MOCK-ORD-")
    assert order.status == "CREATED"
    assert order.total_amount == 3899.00
    assert order.currency == "INR"
    assert order.is_mock is True
    assert len(order.links) > 0


@pytest.mark.asyncio
async def test_capture_order_mock(mock_paypal_client, sample_proposal):
    order = await mock_paypal_client.create_order(sample_proposal, request_id="req_002")
    captured = await mock_paypal_client.capture_order(
        order.order_id, request_id="req_002_cap"
    )

    assert captured.order_id == order.order_id
    assert captured.status == "COMPLETED"
    assert captured.capture_id is not None
    assert captured.capture_id.startswith("MOCK-CAP-")


@pytest.mark.asyncio
async def test_reconcile_order_details_mock(mock_paypal_client, sample_proposal):
    order = await mock_paypal_client.create_order(sample_proposal, request_id="req_003")
    details = await mock_paypal_client.get_order_details(order.order_id)

    assert details.order_id == order.order_id
    assert details.status == "CREATED"

    # Capture and then reconcile again
    await mock_paypal_client.capture_order(order.order_id, request_id="req_003_cap")
    details_after_cap = await mock_paypal_client.get_order_details(order.order_id)
    assert details_after_cap.status == "COMPLETED"
    assert details_after_cap.capture_id is not None
