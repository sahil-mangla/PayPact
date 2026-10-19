from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any, Dict, List, Optional
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
            base_url
            or os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        ).rstrip("/")
        
        # If credentials are not provided or mock_mode explicitly enabled, default to mock
        env_mock = os.getenv("PAYPAL_MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = (
            mock_mode
            if mock_mode is not None
            else (env_mock or not (self.client_id and self.client_secret))
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

        # Build PayPal v2 Order Payload
        items_payload = [
            {
                "name": item.name[:127],
                "sku": item.sku[:127],
                "quantity": str(item.quantity),
                "unit_amount": {
                    "currency_code": proposal.currency,
                    "value": f"{item.unit_price:.2f}",
                },
            }
            for item in proposal.items
        ]

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": proposal.proposal_id,
                    "description": f"Purchase proposal {proposal.proposal_id}",
                    "custom_id": proposal.proposal_fingerprint or "",
                    "amount": {
                        "currency_code": proposal.currency,
                        "value": f"{proposal.total_amount:.2f}",
                        "breakdown": {
                            "item_total": {
                                "currency_code": proposal.currency,
                                "value": f"{proposal.item_subtotal:.2f}",
                            },
                            "shipping": {
                                "currency_code": proposal.currency,
                                "value": f"{proposal.shipping_fee:.2f}",
                            },
                            "tax_total": {
                                "currency_code": proposal.currency,
                                "value": f"{proposal.tax_fee:.2f}",
                            },
                        },
                    },
                    "items": items_payload,
                }
            ],
            "application_context": {
                "return_url": "https://localhost:3000/checkout/success",
                "cancel_url": "https://localhost:3000/checkout/cancel",
                "user_action": "PAY_NOW",
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
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
            resp.raise_for_status()
            data = resp.json()

        # Extract capture id from purchase_units
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
            status=data.get("status", "COMPLETED"),
            intent="CAPTURE",
            create_time=data.get("create_time"),
            capture_id=capture_id,
            total_amount=amount_val,
            currency=currency_val,
            links=data.get("links", []),
            raw_response=data,
            is_mock=False,
        )

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
