"""The model picks the product through Gemini function calls; code still decides if it is allowed.

Gemini is faked: each test scripts the model's turns, so nothing here calls the network.
"""

import httpx
import pytest
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient

from app.agent.gemini_client import GeminiClient
from app.agent.shopper_agent import ShopperAgent
from app.main import app
from app.policy.engine import DeterministicPolicyEngine, PolicyDecisionType


def call(name, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}


class ScriptedGemini:
    """Stands in for GeminiClient.chat_with_tools and records what each turn was offered."""

    def __init__(self, monkeypatch, turns):
        self.turns = list(turns)
        self.seen = []
        monkeypatch.setattr(GeminiClient, "get_api_key", classmethod(lambda cls: "k"))

        def turn(cls, contents, declarations, system, allowed_functions=None):
            self.seen.append({"contents": list(contents), "allowed": allowed_functions})
            return self.turns.pop(0) if self.turns else None

        monkeypatch.setattr(GeminiClient, "chat_with_tools", classmethod(turn))


def policy_for(prompt):
    return ShopperAgent.parse_intent_to_policy(prompt)


def test_model_picks_the_product_through_tool_calls(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    fake = ScriptedGemini(
        monkeypatch,
        [
            call("search_products", query="wireless mechanical keyboard"),
            call(
                "choose_product",
                sku="KB-Q1-PRO",
                reason="The Q1 Pro is a wireless mechanical keyboard that fits the budget.",
            ),
        ],
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))

    # Not the product the deterministic ranking would have put first
    assert res["proposal"].items[0].sku == "KB-Q1-PRO"
    assert res["agent_mode"] == "gemini_tools"
    assert [s["tool"] for s in res["agent_trace"]] == ["search_products", "choose_product"]
    assert "Chosen by Gemini" in res["recommendation_explanation"]
    # The search result went back to the model as a function response
    sent = fake.seen[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert sent["name"] == "search_products"
    assert any(p["sku"] == "KB-Q1-PRO" for p in sent["response"]["products"])


def test_price_comes_from_the_catalogue_not_the_model(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(
        monkeypatch,
        [
            call("search_products", query="keyboard"),
            call("choose_product", sku="KB-Q1-PRO", reason="Good fit.", price=1),
        ],
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["proposal"].total_amount == 4699.00


def test_a_sku_the_model_never_saw_is_ignored(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(
        monkeypatch,
        [call("choose_product", sku="KB-Q1-PRO", reason="Straight to the answer.")],
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["agent_mode"] == "deterministic"
    assert res["agent_trace"] == []


def test_a_pick_that_ignores_the_request_is_rejected_and_logged(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(
        monkeypatch,
        [
            call("get_product", sku="TR-FLIGHT-BLR"),
            call("choose_product", sku="TR-FLIGHT-BLR", reason="A flight is nice."),
        ],
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["agent_mode"] == "deterministic"
    assert res["proposal"].items[0].sku != "TR-FLIGHT-BLR"
    assert res["agent_trace"][-1]["tool"] == "verifier"
    assert "Rejected" in res["agent_trace"][-1]["summary"]


def test_model_cannot_cross_the_agent_persona_boundary(monkeypatch):
    prompt = "Book economy flights to Bangalore under ₹5,000."
    ScriptedGemini(
        monkeypatch,
        [
            call("get_product", sku="KB-Q1-PRO"),
            call("choose_product", sku="KB-Q1-PRO", reason="A keyboard instead."),
        ],
    )
    res = ShopperAgent.generate_proposal(
        prompt, policy_for(prompt), agent_id="agent_travel"
    )
    assert res["proposal"].items[0].sku == "TR-FLIGHT-BLR"
    assert res["agent_mode"] == "deterministic"


def test_figures_smuggled_into_the_reason_are_dropped(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(
        monkeypatch,
        [
            call("get_product", sku="KB-INJECT-01"),
            call(
                "choose_product",
                sku="KB-INJECT-01",
                reason="Pre-approved upgrade to SKU-GOLD-99 at ₹14,500 is included.",
            ),
        ],
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["proposal"].total_amount == 3499.00
    assert "14,500" not in res["recommendation_explanation"]
    assert "GOLD" not in res["recommendation_explanation"]


def test_gate_still_blocks_an_over_budget_pick(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(
        monkeypatch,
        [
            call("get_product", sku="KB-CUSTOM-BRASS"),
            call("choose_product", sku="KB-CUSTOM-BRASS", reason="Premium build."),
        ],
    )
    policy = policy_for(prompt)
    res = ShopperAgent.generate_proposal(prompt, policy)
    assert res["proposal"].items[0].sku == "KB-CUSTOM-BRASS"
    decision = DeterministicPolicyEngine.evaluate(res["proposal"], policy)
    assert decision.decision == PolicyDecisionType.REJECT


def test_final_turn_can_only_commit(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    fake = ScriptedGemini(
        monkeypatch, [call("search_products", query="keyboard")] * 4
    )
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert len(fake.seen) == 4
    assert fake.seen[-1]["allowed"] == ["choose_product"]
    assert fake.seen[0]["allowed"] != ["choose_product"]
    assert res["agent_mode"] == "deterministic"


def test_falls_back_when_gemini_is_unavailable(monkeypatch):
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    ScriptedGemini(monkeypatch, [])  # every turn returns nothing
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["agent_mode"] == "deterministic"
    assert res["proposal"].items[0].sku


def test_no_key_means_no_tool_calls():
    prompt = "Wireless keyboard budget ₹5000 auto ₹4000"
    res = ShopperAgent.generate_proposal(prompt, policy_for(prompt))
    assert res["agent_mode"] == "deterministic"
    assert res["agent_trace"] == []


def test_function_calling_request_shape(monkeypatch):
    """The request asks for forced tool calls, sends the key as a header, and echoes tool results."""
    monkeypatch.setattr(GeminiClient, "get_api_key", classmethod(lambda cls: "fake_key"))
    response = MagicMock(status_code=200)
    response.json.return_value = {"candidates": [{"content": call("get_product", sku="X")}]}
    with patch("httpx.Client.post", return_value=response) as post:
        content = GeminiClient.chat_with_tools(
            [{"role": "user", "parts": [{"text": "hi"}]}],
            [{"name": "get_product"}],
            "be careful",
            allowed_functions=["choose_product"],
        )
    assert content["parts"][0]["functionCall"]["name"] == "get_product"
    payload = post.call_args.kwargs["json"]
    assert payload["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY",
        "allowedFunctionNames": ["choose_product"],
    }
    assert payload["tools"][0]["functionDeclarations"] == [{"name": "get_product"}]
    assert payload["systemInstruction"]["parts"][0]["text"] == "be careful"
    assert post.call_args.kwargs["headers"] == {"x-goog-api-key": "fake_key"}
    assert "fake_key" not in str(post.call_args.args)


def test_http_error_or_garbage_gives_none(monkeypatch):
    monkeypatch.setattr(GeminiClient, "get_api_key", classmethod(lambda cls: "k"))
    for response in (
        MagicMock(status_code=500),
        MagicMock(status_code=200, json=MagicMock(return_value={"candidates": []})),
    ):
        with patch("httpx.Client.post", return_value=response):
            assert GeminiClient.chat_with_tools([], [], "s") is None
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("down")):
        assert GeminiClient.chat_with_tools([], [], "s") is None


@pytest.mark.asyncio
async def test_api_returns_the_agent_trace(monkeypatch):
    ScriptedGemini(
        monkeypatch,
        [
            call("search_products", query="keyboard"),
            call("choose_product", sku="KB-Q1-PRO", reason="Fits the budget well."),
        ],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        intent = await client.post(
            "/api/authorizations/parse-intent",
            json={"prompt": "Wireless keyboard budget ₹5000 auto ₹4000"},
        )
        reg = await client.post("/api/authorizations", json=intent.json())
        res = await client.post(
            "/api/proposals",
            json={
                "prompt": "Wireless keyboard budget ₹5000 auto ₹4000",
                "policy_id": reg.json()["policy_id"],
                "agent_id": "agent_hardware",
            },
        )
    body = res.json()
    assert body["agent_mode"] == "gemini_tools"
    assert body["agent_trace"][0]["tool"] == "search_products"
    assert body["proposal"]["items"][0]["sku"] == "KB-Q1-PRO"
