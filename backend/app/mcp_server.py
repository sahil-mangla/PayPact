"""PayPact as an MCP server: any AI agent can search, propose and pay, but never approve.

The tools run on the same coordinator instance as the REST API (app.api.routers.coordinator),
so a purchase an MCP agent proposes shows up in the web UI, where the account owner approves it.
There is deliberately no approve, revoke or policy-creation tool, and no tool output ever carries
an owner token or an approval-link token: those stay with the human owner.

Two ways to run it:
  * streamable HTTP, mounted by app.main at /mcp (the hosted deploy), see mcp_lifespan and mount_mcp
  * stdio, for local clients such as Claude Desktop: `python -m app.mcp_server`
    (a separate process, so it keeps its own in-memory state, not the web UI's)
"""

import app.config  # noqa: F401 — side-effect: loads .env before the coordinator is built

import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from app.api.ratelimit import llm_limiter
from app.api.routers import ExecutePaymentRequest, coordinator, run_execute, run_proposal
from app.catalogue.products import search_catalogue
from app.models.schemas import PolicyDecisionType, TransactionState
from app.policy.engine import DeterministicPolicyEngine
from app.state.machine import CheckoutSession

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"

INSTRUCTIONS = (
    "PayPact guards purchases made on behalf of a human account owner. You can search the catalogue, "
    "propose a purchase under an existing policy (give its policy_id), check a checkout and pay for one. "
    "The owner's policy decides whether a purchase is allowed, needs the owner's approval, or is blocked. "
    "You cannot approve a purchase yourself and there is no tool for it: when approval is needed, "
    "tell the owner and wait. Prices always come from the merchant catalogue, never from the request text."
)

_AWAITING_STEP = (
    "The account owner must approve this purchase; you cannot approve it yourself. "
    "Ask the owner to approve it in PayPact, then call pay with this checkout_id."
)


def _decision(session: CheckoutSession) -> Optional[str]:
    if session.approval_record is not None:
        return "APPROVED_BY_OWNER"
    if session.state == TransactionState.POLICY_REJECTED:
        return PolicyDecisionType.REJECT.value
    if session.state == TransactionState.AWAITING_APPROVAL:
        return PolicyDecisionType.REQUIRE_APPROVAL.value
    if session.state == TransactionState.AUTHORIZED:
        return PolicyDecisionType.ALLOW.value
    return None


def _reasons(session: CheckoutSession) -> List[str]:
    """The plain-words reasons behind the decision, from the same engine the gate uses."""
    if session.failure_reason:
        return [session.failure_reason]
    if session.state == TransactionState.AWAITING_APPROVAL:
        policy = coordinator.get_policy(session.policy_id)
        if policy:
            evaluation = DeterministicPolicyEngine.evaluate(session.proposal, policy)
            failed = [c.reason for c in evaluation.checks if not c.passed]
            return failed or [evaluation.primary_reason]
    return []


def _next_step(session: CheckoutSession) -> str:
    state = session.state
    if state == TransactionState.AWAITING_APPROVAL:
        return _AWAITING_STEP
    if state == TransactionState.AUTHORIZED:
        return "The owner's policy allows this purchase. Call pay with this checkout_id to complete it."
    if state == TransactionState.POLICY_REJECTED:
        return "The owner's policy blocks this purchase. Do not retry it; tell the owner why."
    if state == TransactionState.PAID:
        return "Paid. Nothing more to do."
    if state in (TransactionState.CHECKOUT_CREATED, TransactionState.PAYMENT_PENDING):
        return "Waiting for the buyer to approve the payment in PayPal."
    if state == TransactionState.RECONCILIATION_REQUIRED:
        return "The payment outcome is unclear. Do not pay again; the owner must reconcile it in PayPact."
    return "This checkout cannot be paid. Tell the owner."


def _sentence(session: CheckoutSession) -> str:
    proposal = session.proposal
    what = ", ".join(f"{i.quantity} x {i.name}" for i in proposal.items)
    deal = f"{what} from {proposal.merchant} for {proposal.total_amount:.2f} {proposal.currency}"
    state = session.state
    if state == TransactionState.AWAITING_APPROVAL:
        return f"Needs the account owner's approval: {deal}. The agent cannot approve it."
    if state == TransactionState.AUTHORIZED:
        return f"Allowed by the owner's policy: {deal}."
    if state == TransactionState.POLICY_REJECTED:
        return f"Blocked by the owner's policy: {deal}."
    if state == TransactionState.PAID:
        return f"Paid: {deal}."
    return f"{deal} (state {state.value})."


def _view(session: CheckoutSession) -> Dict[str, Any]:
    """What an agent may see of a checkout: money, decision, reasons. Never a token."""
    proposal = session.proposal
    return {
        "checkout_id": session.checkout_id,
        "state": session.state.value,
        "decision": _decision(session),
        "summary": _sentence(session),
        "reasons": _reasons(session),
        "merchant": proposal.merchant,
        "items": [
            {"sku": i.sku, "name": i.name, "quantity": i.quantity, "unit_price": i.unit_price}
            for i in proposal.items
        ],
        "item_subtotal": proposal.item_subtotal,
        "shipping_fee": proposal.shipping_fee,
        "tax_fee": proposal.tax_fee,
        "total": proposal.total_amount,
        "currency": proposal.currency,
        "failure_reason": session.failure_reason,
        "next_step": _next_step(session),
    }


def _client_key(ctx: Optional[Context]) -> str:
    """Rate-limit bucket: the calling host over HTTP, one shared bucket otherwise (stdio)."""
    try:
        request = ctx.request_context.request if ctx else None
        client = getattr(request, "client", None)
        if client and client.host:
            return f"mcp:{client.host}"
    except Exception:
        pass
    return "mcp:local"


def build_mcp_server() -> FastMCP:
    """A fresh FastMCP instance. The HTTP session manager runs once per instance, so each app
    startup builds its own (the tools hold no state of their own)."""
    server = FastMCP(
        "PayPact",
        instructions=INSTRUCTIONS,
        streamable_http_path=MCP_PATH,
        # The default only trusts localhost Host headers, which would refuse the hosted deploy.
        # This endpoint has no cookies and no ambient credentials, so there is nothing for a
        # DNS-rebinding page to ride on; the owner's secrets never pass through it.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool()
    async def search_products(
        query: Annotated[str, Field(min_length=2, max_length=200, description="What to look for, e.g. 'wireless mechanical keyboard'")],
    ) -> Dict[str, Any]:
        """Search the merchant catalogue. Returns a compact list of products with their real prices."""
        products = search_catalogue(query, max_results=5)
        return {
            "count": len(products),
            "products": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "merchant": p.merchant,
                    "category": p.category,
                    "price": p.unit_price,
                    "shipping_fee": p.shipping_fee,
                    "currency": p.currency,
                    "in_stock": p.in_stock,
                }
                for p in products
            ],
        }

    @server.tool()
    async def propose_purchase(
        policy_id: Annotated[str, Field(min_length=1, max_length=64, description="The owner's authorization policy id")],
        request: Annotated[str, Field(min_length=2, max_length=500, description="What to buy, in plain words")],
        agent_id: Annotated[str, Field(max_length=64)] = "agent_hardware",
        ctx: Optional[Context] = None,
    ) -> Dict[str, Any]:
        """Propose a purchase under the owner's policy.

        The shopper agent picks a product, prices it from the catalogue and the policy gate decides:
        ALLOW (call pay next), REQUIRE_APPROVAL (the owner must approve; you cannot) or REJECT.
        """
        try:
            llm_limiter.check(_client_key(ctx))
            result = await run_proposal(request, policy_id, agent_id=agent_id)
        except HTTPException as exc:
            return {
                "ok": False,
                "summary": f"Nothing was proposed: {exc.detail}",
                "next_step": "Change the request or ask the owner; do not retry unchanged."
                if exc.status_code != 429
                else "Slow down and retry shortly.",
            }
        session = coordinator.get_session(result["checkout_id"])
        return {"ok": True, **_view(session)}

    @server.tool()
    async def get_checkout(
        checkout_id: Annotated[str, Field(min_length=1, max_length=64)],
    ) -> Dict[str, Any]:
        """Look up a checkout: its state, the decision and reasons, amounts and any failure reason."""
        session = coordinator.get_session(checkout_id)
        if not session:
            return {"ok": False, "summary": f"Checkout '{checkout_id}' was not found."}
        return {"ok": True, **_view(session)}

    @server.tool()
    async def pay(
        checkout_id: Annotated[str, Field(min_length=1, max_length=64)],
    ) -> Dict[str, Any]:
        """Pay for an authorized checkout. The policy gate re-checks everything first.

        Refused while the owner's approval is outstanding. With live PayPal this returns a URL
        the buyer (a human) must open to approve the payment; with the mock it completes at once.
        """
        try:
            result = await run_execute(checkout_id, ExecutePaymentRequest())
        except HTTPException as exc:
            session = coordinator.get_session(checkout_id)
            if session is None:
                return {"ok": False, "paid": False, "summary": f"Checkout '{checkout_id}' was not found."}
            detail = str(exc.detail)
            if session.state == TransactionState.AWAITING_APPROVAL:
                detail = "The account owner has not approved this purchase yet."
            return {
                "ok": False,
                "paid": False,
                **_view(session),
                "summary": f"Payment refused: {detail}",
            }
        done: CheckoutSession = result["session"]
        view = _view(done)
        paid = done.state == TransactionState.PAID
        out: Dict[str, Any] = {"ok": paid or bool(result.get("needs_buyer_approval")), "paid": paid, **view}
        if result.get("needs_buyer_approval") and result.get("approve_url"):
            out["buyer_approval_url"] = result["approve_url"]
            out["summary"] = "Payment created in PayPal. The buyer must open the link to approve it."
            out["next_step"] = (
                "Give buyer_approval_url to the human buyer; they approve in PayPal. "
                "You cannot complete this step."
            )
        elif not paid:
            out["summary"] = f"Payment did not go through: {done.failure_reason or view['summary']}"
        return out

    return server


# ----- mounting into the FastAPI app -----
class _McpGateway:
    """ASGI endpoint for /mcp that forwards to whichever MCP server the running app started."""

    def __init__(self) -> None:
        self.server: Optional[FastMCP] = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        server = self.server
        if server is None:
            body = json.dumps({"detail": "The MCP endpoint is not running."}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await server.session_manager.handle_request(scope, receive, send)


_gateway = _McpGateway()


@asynccontextmanager
async def mcp_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: start the MCP session manager's task group for as long as the app runs."""
    server = build_mcp_server()
    server.streamable_http_app()  # creates server.session_manager
    async with server.session_manager.run():
        _gateway.server = server
        try:
            yield
        finally:
            _gateway.server = None


def mount_mcp(app: FastAPI) -> None:
    """Serve streamable HTTP MCP at /mcp. The app must be created with lifespan=mcp_lifespan."""
    app.add_route(MCP_PATH, _gateway, include_in_schema=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO)  # stderr: stdout belongs to the MCP protocol
    build_mcp_server().run("stdio")


if __name__ == "__main__":
    main()
