from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional
import httpx
from pydantic import BaseModel, Field

from app.models.schemas import PurchaseProposal


class PayPalOrderResponse(BaseModel):
    order_id: str
    status: str
    intent: str
    create_time: Optional[str] = None
    capture_id: Optional[str] = None
    payer_id: Optional[str] = None
    total_amount: float
    currency: str
    links: List[Dict[str, str]] = Field(default_factory=list)
    raw_response: Dict[str, Any] = Field(default_factory=dict)
    is_mock: bool = False
    amount_reported: bool = True


# PayPal REST currencies this client will send. INR is not one of them: the sandbox demo
# converts it to USD at a fixed rate (override with INR_TO_USD_RATE). Any other currency is
# refused rather than charged 1:1 under a different name.
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "SGD", "JPY", "CHF", "NZD", "HKD"}
ZERO_DECIMAL_CURRENCIES = {"JPY"}


class PayPalCharge(BaseModel):
    """What PayPal will actually be asked to charge for a proposal."""

    currency: str
    items: List[Dict[str, Any]]
    item_total_value: str
    shipping_value: str
    tax_value: str
    total_value: str

    @property
    def total(self) -> float:
        return float(self.total_value)


class PayPalClient:
    """PayPal REST API v2 Client for Sandbox Orders and Idempotent Captures.

    Adheres strictly to PayPal Developer Guidelines:
    - Uses OAuth2 client_credentials token caching.
    - Sends PayPal-Request-Id on every mutating call for gateway idempotency.
    - Provides get_order_details for post-timeout reconciliation.
    - Supports simulated offline mode for reproducible benchmark evaluations.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.client_id = client_id or os.getenv("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("PAYPAL_CLIENT_SECRET", "")
        self.base_url = (
            base_url or os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        ).rstrip("/")

        # If credentials are not provided or mock_mode explicitly enabled, default to mock
        env_mock = os.getenv("PAYPAL_MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = (
            mock_mode
            if mock_mode is not None
            else (env_mock or not (self.client_id and self.client_secret))
        )

        # Where PayPal sends the buyer back after approval (the JS SDK flow uses callbacks)
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip(
            "/"
        )

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._mock_orders_store: Dict[str, Dict[str, Any]] = {}

    async def get_access_token(self) -> str:
        """Fetch or return cached OAuth2 access token."""
        if self.mock_mode:
            return "mock_access_token_paypal_sandbox"

        now = time.time()
        if self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                headers=headers,
                data=data,
            )
            resp.raise_for_status()
            payload = resp.json()

        self._access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._token_expires_at = now + expires_in
        return self._access_token

    def charge_for(self, proposal: PurchaseProposal) -> PayPalCharge:
        """Work out the exact PayPal charge (currency, line items, totals) for a proposal."""
        currency = proposal.currency.upper()
        rate = 1.0
        if currency == "INR":
            currency = "USD"
            rate = 1.0 / float(os.getenv("INR_TO_USD_RATE", "83"))
        elif currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Currency '{proposal.currency}' is not supported by PayPal checkout."
            )

        digits = 0 if currency in ZERO_DECIMAL_CURRENCIES else 2

        def fmt(value: float) -> str:
            return f"{value:.{digits}f}"

        items_payload = []
        item_total_sum = 0.0
        for item in proposal.items:
            unit_val = round(item.unit_price * rate, digits)
            item_total_sum += round(unit_val * item.quantity, digits)
            items_payload.append(
                {
                    "name": (item.name.strip() or "Item")[:127],
                    "sku": (item.sku.strip() or "SKU")[:127],
                    "quantity": str(item.quantity),
                    "unit_amount": {
                        "currency_code": currency,
                        "value": fmt(unit_val),
                    },
                }
            )

        item_total_sum = round(item_total_sum, digits)
        shipping_val = round(proposal.shipping_fee * rate, digits)
        tax_val = round(proposal.tax_fee * rate, digits)
        total_val = round(item_total_sum + shipping_val + tax_val, digits)
        return PayPalCharge(
            currency=currency,
            items=items_payload,
            item_total_value=fmt(item_total_sum),
            shipping_value=fmt(shipping_val),
            tax_value=fmt(tax_val),
            total_value=fmt(total_val),
        )

    def expected_charge(self, proposal: PurchaseProposal) -> tuple[str, float]:
        """Currency and amount a successful capture of this proposal must report."""
        if self.mock_mode:
            return proposal.currency, proposal.total_amount
        charge = self.charge_for(proposal)
        return charge.currency, charge.total

    async def create_order(
        self,
        proposal: PurchaseProposal,
        request_id: Optional[str] = None,
    ) -> PayPalOrderResponse:
        """Create a PayPal v2 Checkout Order with idempotency header."""
        req_id = request_id or str(uuid.uuid4())

        if self.mock_mode:
            order_id = f"MOCK-ORD-{uuid.uuid4().hex[:8].upper()}"
            mock_order = {
                "id": order_id,
                "status": "CREATED",
                "intent": "CAPTURE",
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "amount": proposal.total_amount,
                "currency": proposal.currency,
                "request_id": req_id,
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "links": [
                    {
                        "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                        "rel": "approve",
                        "method": "GET",
                    }
                ],
            }
            self._mock_orders_store[order_id] = mock_order
            return PayPalOrderResponse(
                order_id=order_id,
                status="CREATED",
                intent="CAPTURE",
                create_time=mock_order["create_time"],
                total_amount=proposal.total_amount,
                currency=proposal.currency,
                links=mock_order["links"],
                raw_response=mock_order,
                is_mock=True,
            )

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": req_id,
        }

        charge = self.charge_for(proposal)

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": proposal.proposal_id,
                    "description": f"Purchase proposal {proposal.proposal_id}",
                    "custom_id": proposal.proposal_fingerprint or "",
                    "amount": {
                        "currency_code": charge.currency,
                        "value": charge.total_value,
                        "breakdown": {
                            "item_total": {
                                "currency_code": charge.currency,
                                "value": charge.item_total_value,
                            },
                            "shipping": {
                                "currency_code": charge.currency,
                                "value": charge.shipping_value,
                            },
                            "tax_total": {
                                "currency_code": charge.currency,
                                "value": charge.tax_value,
                            },
                        },
                    },
                    "items": charge.items,
                }
            ],
            "application_context": {
                "return_url": f"{self.frontend_url}/checkout/success",
                "cancel_url": f"{self.frontend_url}/checkout/cancel",
                "user_action": "PAY_NOW",
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=headers,
                json=payload,
            )
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    err_msg = (
                        err_json.get("message")
                        or (err_json.get("details", [{}])[0].get("description"))
                        or resp.text
                    )
                except Exception:
                    err_msg = resp.text
                raise RuntimeError(
                    f"PayPal order creation rejected ({resp.status_code}): {err_msg}"
                )
            data = resp.json()

        return PayPalOrderResponse(
            order_id=data["id"],
            status=data.get("status", "CREATED"),
            intent=data.get("intent", "CAPTURE"),
            create_time=data.get("create_time"),
            total_amount=proposal.total_amount,
            currency=proposal.currency,
            links=data.get("links", []),
            raw_response=data,
            is_mock=False,
        )

    async def capture_order(
        self,
        order_id: str,
        request_id: Optional[str] = None,
    ) -> PayPalOrderResponse:
        """Capture payment for an approved PayPal Order with idempotency header."""
        req_id = request_id or str(uuid.uuid4())

        if self.mock_mode:
            if order_id not in self._mock_orders_store:
                raise ValueError(f"Mock order '{order_id}' not found.")
            order = self._mock_orders_store[order_id]
            order["status"] = "COMPLETED"
            capture_id = f"MOCK-CAP-{uuid.uuid4().hex[:8].upper()}"
            order["capture_id"] = capture_id
            return PayPalOrderResponse(
                order_id=order_id,
                status="COMPLETED",
                intent="CAPTURE",
                create_time=order.get("create_time"),
                capture_id=capture_id,
                total_amount=order["amount"],
                currency=order["currency"],
                links=order.get("links", []),
                raw_response=order,
                is_mock=True,
            )

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": req_id,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers=headers,
            )
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    err_msg = (
                        err_json.get("message")
                        or (err_json.get("details", [{}])[0].get("description"))
                        or resp.text
                    )
                except Exception:
                    err_msg = resp.text
                raise RuntimeError(
                    f"PayPal capture rejected ({resp.status_code}): {err_msg}"
                )
            data = resp.json()

        # Extract capture id from purchase_units
        capture_id = None
        purchase_units = data.get("purchase_units", [])
        if purchase_units:
            captures = purchase_units[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id")

        # A capture response reports what was captured under payments.captures[]; the order
        # amount on the purchase unit is only a fallback.
        amount_val = 0.0
        currency_val = "USD"
        amount_reported = False
        amt = None
        if purchase_units:
            captures = purchase_units[0].get("payments", {}).get("captures", [])
            if captures and captures[0].get("amount"):
                amt = captures[0]["amount"]
            elif purchase_units[0].get("amount"):
                amt = purchase_units[0]["amount"]
        if amt and amt.get("value") is not None:
            amount_val = float(amt["value"])
            currency_val = amt.get("currency_code", "USD")
            amount_reported = True

        return PayPalOrderResponse(
            order_id=data["id"],
            status=data.get("status", "COMPLETED"),
            intent="CAPTURE",
            create_time=data.get("create_time"),
            capture_id=capture_id,
            total_amount=amount_val,
            currency=currency_val,
            links=data.get("links", []),
            raw_response=data,
            is_mock=False,
            amount_reported=amount_reported,
        )

    async def verify_webhook_signature(
        self,
        headers: Mapping[str, str],
        event: Dict[str, Any],
        webhook_id: str,
    ) -> bool:
        """Verify a webhook delivery through PayPal's verify-webhook-signature API.

        Fails closed: any missing transmission header, rejected call or non-SUCCESS
        verdict returns False. Mock mode has no PayPal to ask, so it never verifies.
        """
        if self.mock_mode or not webhook_id:
            return False

        # Starlette lower-cases incoming header names
        lowered = {k.lower(): v for k, v in headers.items()}
        fields = {
            "auth_algo": "paypal-auth-algo",
            "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id",
            "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }
        payload: Dict[str, Any] = {}
        for field, header in fields.items():
            value = lowered.get(header)
            if not value:
                return False
            payload[field] = value
        payload["webhook_id"] = webhook_id
        payload["webhook_event"] = event

        token = await self.get_access_token()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/notifications/verify-webhook-signature",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code >= 400:
                return False
            return resp.json().get("verification_status") == "SUCCESS"
        except (httpx.HTTPError, ValueError):
            return False

    async def get_order_details(self, order_id: str) -> PayPalOrderResponse:
        """Fetch current order details for post-timeout state reconciliation."""
        if self.mock_mode:
            if order_id not in self._mock_orders_store:
                raise ValueError(f"Mock order '{order_id}' not found.")
            order = self._mock_orders_store[order_id]
            return PayPalOrderResponse(
                order_id=order_id,
                status=order.get("status", "UNKNOWN"),
                intent=order.get("intent", "CAPTURE"),
                create_time=order.get("create_time"),
                capture_id=order.get("capture_id"),
                total_amount=order.get("amount", 0.0),
                currency=order.get("currency", "USD"),
                links=order.get("links", []),
                raw_response=order,
                is_mock=True,
            )

        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        capture_id = None
        purchase_units = data.get("purchase_units", [])
        if purchase_units:
            captures = purchase_units[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id")

        amount_val = 0.0
        currency_val = "USD"
        if purchase_units and "amount" in purchase_units[0]:
            amt = purchase_units[0]["amount"]
            amount_val = float(amt.get("value", 0.0))
            currency_val = amt.get("currency_code", "USD")

        return PayPalOrderResponse(
            order_id=data["id"],
            status=data.get("status", "UNKNOWN"),
            intent=data.get("intent", "CAPTURE"),
            create_time=data.get("create_time"),
            capture_id=capture_id,
            total_amount=amount_val,
            currency=currency_val,
            links=data.get("links", []),
            raw_response=data,
            is_mock=False,
        )
