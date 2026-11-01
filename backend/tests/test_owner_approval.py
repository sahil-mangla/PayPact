"""Owner token and one-time approval links: an agent can propose but never approve."""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routers import coordinator
from app.main import app
from app.state import machine

APPROVAL_PROMPT = "Find a mechanical keyboard under ₹5,000, auto-buy under ₹1,000"
AUTO_PROMPT = "Find a mechanical keyboard under ₹5,000, auto-buy under ₹4,000"
OWNER = "X-Owner-Token"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _awaiting(client: AsyncClient, prompt: str = APPROVAL_PROMPT):
    """Register a policy and propose a purchase. Returns (owner_token, policy_id, checkout_id)."""
    intent = (
        await client.post("/api/authorizations/parse-intent", json={"prompt": prompt})
    ).json()
    registered = (await client.post("/api/authorizations", json=intent)).json()
    proposal = (
        await client.post(
            "/api/proposals",
            json={
                "prompt": "Keychron K2 wireless mechanical keyboard",
                "policy_id": registered["policy_id"],
            },
        )
    ).json()
    return registered["owner_token"], registered["policy_id"], proposal["checkout_id"]


def _denied_events(checkout_id=None):
    return coordinator.audit_ledger.get_events(
        checkout_id=checkout_id, event_type="APPROVAL_DENIED"
    )


@pytest.mark.asyncio
async def test_registration_returns_the_owner_token_once_and_never_again():
    async with _client() as client:
        token, policy_id, checkout_id = await _awaiting(client)
        assert len(token) >= 40

        # No read endpoint may carry the token or its hash.
        stored_hash = coordinator.get_policy(policy_id)._owner_token_hash
        assert stored_hash and stored_hash != token
        urls = [
            f"/api/authorizations/{policy_id}",
            f"/api/checkouts/{checkout_id}",
            f"/api/checkouts/{checkout_id}/receipt",
            "/api/audit/events",
            f"/api/audit/events?checkout_id={checkout_id}",
        ]
        for url in urls:
            body = (await client.get(url)).text
            assert token not in body, url
            assert stored_hash not in body, url
            # (the audit trail legitimately says `"via": "owner_token"`; only a field would be a leak)
            assert '"owner_token":' not in body, url


@pytest.mark.asyncio
async def test_approve_without_a_token_is_401_and_audited():
    async with _client() as client:
        _, _, checkout_id = await _awaiting(client)
        resp = await client.post(f"/api/checkouts/{checkout_id}/approve", json={})
        assert resp.status_code == 401

        events = _denied_events(checkout_id)
        assert len(events) == 1
        assert events[0].metadata["action"] == "approve"
        assert "no owner token" in events[0].reason
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_approve_with_a_wrong_token_is_403_audited_and_does_not_log_the_token():
    async with _client() as client:
        _, _, checkout_id = await _awaiting(client)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/approve",
            json={},
            headers={OWNER: "agent-guess-123"},
        )
        assert resp.status_code == 403

        events = _denied_events(checkout_id)
        assert len(events) == 1
        assert "did not match" in events[0].reason
        assert "agent-guess-123" not in events[0].model_dump_json()
        assert coordinator.audit_ledger.verify_ledger_integrity()


@pytest.mark.asyncio
async def test_a_token_from_another_policy_cannot_approve():
    async with _client() as client:
        _, _, checkout_id = await _awaiting(client)
        other_token, _, _ = await _awaiting(client)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/approve", json={}, headers={OWNER: other_token}
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_token_approves():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/approve", json={}, headers={OWNER: token}
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "AUTHORIZED"
        assert not _denied_events(checkout_id)


@pytest.mark.asyncio
async def test_revoke_requires_the_owner_token():
    async with _client() as client:
        token, policy_id, _ = await _awaiting(client)
        url = f"/api/authorizations/{policy_id}/revoke"

        assert (await client.post(url)).status_code == 401
        assert (await client.post(url, headers={OWNER: "nope"})).status_code == 403
        assert (await client.get(f"/api/authorizations/{policy_id}")).json()[
            "is_revoked"
        ] is False
        denied = _denied_events()
        assert [e.metadata["action"] for e in denied][-2:] == ["revoke", "revoke"]

        assert (await client.post(url, headers={OWNER: token})).status_code == 200
        assert (await client.get(f"/api/authorizations/{policy_id}")).json()[
            "is_revoked"
        ] is True


@pytest.mark.asyncio
async def test_unknown_checkout_and_policy_stay_404():
    async with _client() as client:
        resp = await client.post("/api/checkouts/chk_nope/approve", json={})
        assert resp.status_code == 404
        resp = await client.post("/api/authorizations/pol_nope/revoke")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_internally_registered_policy_has_no_token_so_http_approval_is_refused():
    from app.agent.shopper_agent import ShopperAgent

    async with _client() as client:
        policy = ShopperAgent.parse_intent_to_policy(APPROVAL_PROMPT, user_id="usr_x")
        coordinator.register_policy(policy)  # no owner token issued
        proposal = (
            await client.post(
                "/api/proposals",
                json={"prompt": "Keychron K2 keyboard", "policy_id": policy.policy_id},
            )
        ).json()
        resp = await client.post(
            f"/api/checkouts/{proposal['checkout_id']}/approve",
            json={},
            headers={OWNER: "anything"},
        )
        assert resp.status_code == 403


# ---------- approval links ----------
async def _link(client, token, checkout_id):
    resp = await client.post(
        f"/api/checkouts/{checkout_id}/approval-link", headers={OWNER: token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["approval_url"].rsplit("/", 1)[1], body


@pytest.mark.asyncio
async def test_minting_a_link_needs_the_owner_token():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        url = f"/api/checkouts/{checkout_id}/approval-link"
        assert (await client.post(url)).status_code == 401
        assert (await client.post(url, headers={OWNER: "x"})).status_code == 403
        assert len(_denied_events(checkout_id)) == 2

        link_token, body = await _link(client, token, checkout_id)
        assert body["approval_url"] == f"http://localhost:3000/approve/{link_token}"
        assert "expires_at" in body


@pytest.mark.asyncio
async def test_link_base_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://paypact.example.com/")
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, body = await _link(client, token, checkout_id)
        assert body["approval_url"] == f"https://paypact.example.com/approve/{link_token}"


@pytest.mark.asyncio
async def test_link_base_url_falls_back_to_frontend_url(monkeypatch):
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
    monkeypatch.setenv("FRONTEND_URL", "https://paypact-frontend.example.com/")
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, body = await _link(client, token, checkout_id)
        assert body["approval_url"] == (
            f"https://paypact-frontend.example.com/approve/{link_token}"
        )

        # FRONTEND_BASE_URL wins when both are set.
        monkeypatch.setenv("FRONTEND_BASE_URL", "https://paypact.example.com")
        link_token, body = await _link(client, token, checkout_id)
        assert body["approval_url"] == f"https://paypact.example.com/approve/{link_token}"


@pytest.mark.asyncio
async def test_a_checkout_that_needs_no_approval_gets_no_link():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client, AUTO_PROMPT)
        resp = await client.post(
            f"/api/checkouts/{checkout_id}/approval-link", headers={OWNER: token}
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_summary_describes_the_purchase_without_approving_it():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, body = await _link(client, token, checkout_id)

        summary = (await client.get(f"/api/approvals/{link_token}")).json()
        assert summary["checkout_id"] == checkout_id
        assert summary["merchant"]
        assert summary["items"] and summary["items"][0]["sku"]
        assert summary["total_amount"] > 1000
        assert summary["currency"] == "INR"
        assert summary["decision"] == "REQUIRE_APPROVAL"
        assert summary["reasons"]
        assert summary["expires_at"]
        # Reading it twice is harmless, and nothing was approved.
        assert (await client.get(f"/api/approvals/{link_token}")).status_code == 200
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_a_link_approves_exactly_once_and_payment_then_works():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, _ = await _link(client, token, checkout_id)

        # The agent has no token, so it cannot pay before approval is given.
        blocked = await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        assert blocked.status_code == 400
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AWAITING_APPROVAL"

        approved = await client.post(f"/api/approvals/{link_token}")
        assert approved.status_code == 200
        assert approved.json()["state"] == "AUTHORIZED"
        approvals = coordinator.audit_ledger.get_events(
            checkout_id=checkout_id, event_type="USER_APPROVED"
        )
        assert approvals[-1].metadata["via"] == "approval_link"

        again = await client.post(f"/api/approvals/{link_token}")
        assert again.status_code == 410
        assert "already been used" in again.json()["detail"]
        assert (await client.get(f"/api/approvals/{link_token}")).status_code == 410
        assert any("already" in e.reason for e in _denied_events(checkout_id))

        paid = await client.post(f"/api/checkouts/{checkout_id}/execute", json={})
        assert paid.json()["session"]["state"] == "PAID"


@pytest.mark.asyncio
async def test_unknown_link_is_404():
    async with _client() as client:
        assert (await client.get("/api/approvals/not-a-real-token")).status_code == 404
        assert (await client.post("/api/approvals/not-a-real-token")).status_code == 404


@pytest.mark.asyncio
async def test_an_expired_link_is_refused(monkeypatch):
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, body = await _link(client, token, checkout_id)

        real_now = machine._now
        monkeypatch.setattr(
            machine,
            "_now",
            lambda: real_now() + machine.APPROVAL_LINK_TTL + timedelta(seconds=1),
        )
        resp = await client.post(f"/api/approvals/{link_token}")
        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"]
        assert (await client.get(f"/api/approvals/{link_token}")).status_code == 410

        monkeypatch.setattr(machine, "_now", real_now)
        state = (await client.get(f"/api/checkouts/{checkout_id}")).json()["state"]
        assert state == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_a_link_is_refused_once_the_proposal_drifted():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, _ = await _link(client, token, checkout_id)

        session = coordinator.get_session(checkout_id)
        session.proposal.shipping_fee += 100.0
        session.proposal.total_amount += 100.0

        for call in (client.get, client.post):
            resp = await call(f"/api/approvals/{link_token}")
            assert resp.status_code == 409
            assert "changed" in resp.json()["detail"]
        assert session.state.value == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_a_new_link_replaces_the_old_one_and_links_are_stored_hashed():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        first, _ = await _link(client, token, checkout_id)
        second, _ = await _link(client, token, checkout_id)

        assert (await client.get(f"/api/approvals/{first}")).status_code == 404
        assert (await client.get(f"/api/approvals/{second}")).status_code == 200
        assert second not in coordinator._approval_links
        assert machine.hash_token(second) in coordinator._approval_links


@pytest.mark.asyncio
async def test_a_link_for_a_checkout_approved_by_token_is_dead():
    async with _client() as client:
        token, _, checkout_id = await _awaiting(client)
        link_token, _ = await _link(client, token, checkout_id)
        await client.post(
            f"/api/checkouts/{checkout_id}/approve", json={}, headers={OWNER: token}
        )
        resp = await client.post(f"/api/approvals/{link_token}")
        assert resp.status_code == 410
        assert "no longer needs approval" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_token_endpoints_are_rate_limited(monkeypatch):
    from app.api.ratelimit import token_limiter

    monkeypatch.setattr(token_limiter, "_limit", lambda: 3)
    async with _client() as client:
        codes = [
            (await client.get("/api/approvals/not-a-real-token")).status_code
            for _ in range(5)
        ]
        assert codes[:3] == [404, 404, 404]
        assert codes[3:] == [429, 429]


@pytest.mark.asyncio
async def test_owner_can_list_their_policys_checkouts_newest_first():
    async with _client() as client:
        token, policy_id, first = await _awaiting(client)
        second = (
            await client.post(
                "/api/proposals",
                json={
                    "prompt": "Keychron K2 wireless mechanical keyboard",
                    "policy_id": policy_id,
                    "agent_id": "agent_outside",
                },
            )
        ).json()["checkout_id"]
        # A checkout under another policy must not leak into this list.
        _, _, foreign = await _awaiting(client)

        resp = await client.get(
            f"/api/authorizations/{policy_id}/checkouts", headers={OWNER: token}
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert [r["checkout_id"] for r in rows] == [second, first]
        assert foreign not in [r["checkout_id"] for r in rows]
        row = rows[0]
        assert row["agent_id"] == "agent_outside"
        assert rows[1]["state"] == "AWAITING_APPROVAL"
        assert rows[1]["failure_reason"] is None
        if row["state"] == "POLICY_REJECTED":
            assert row["failure_reason"]
        assert row["merchant"] and row["currency"] and row["total_amount"] > 0
        assert row["items"][0]["name"]
        assert row["created_at"]
        assert "failure_reason" in row
        # Never carries a secret.
        assert token not in resp.text
        assert "_owner_token_hash" not in resp.text


@pytest.mark.asyncio
async def test_listing_checkouts_requires_the_owner_token_and_is_audited():
    async with _client() as client:
        token, policy_id, _ = await _awaiting(client)
        url = f"/api/authorizations/{policy_id}/checkouts"

        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={OWNER: "guess"})).status_code == 403
        other_token, _, _ = await _awaiting(client)
        assert (await client.get(url, headers={OWNER: other_token})).status_code == 403
        assert (await client.get(url, headers={OWNER: token})).status_code == 200

        denied = [e for e in _denied_events() if e.metadata["action"] == "list-checkouts"]
        assert len(denied) == 3


@pytest.mark.asyncio
async def test_listing_checkouts_for_an_unknown_policy_is_404():
    async with _client() as client:
        resp = await client.get(
            "/api/authorizations/pol_nope/checkouts", headers={OWNER: "x"}
        )
        assert resp.status_code == 404
