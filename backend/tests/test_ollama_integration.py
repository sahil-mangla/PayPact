import pytest
from app.agent.ollama_client import OllamaClient
from app.agent.shopper_agent import ShopperAgent


def test_ollama_client_health():
    info = OllamaClient.check_health()
    assert "available" in info
    assert "model" in info
    assert info["model"] == "qwen2.5-coder:7b"


def test_shopper_agent_with_ollama_or_fallback():
    prompt = "Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000."
    policy = ShopperAgent.parse_intent_to_policy(prompt)

    assert policy.product_category == "mechanical keyboard"
    assert policy.maximum_total == 5000.0
    assert policy.automatic_purchase_limit == 4000.0
    assert policy.allowed_currencies == ["INR", "USD"]
    assert "agent_hardware" in policy.agent_quotas

    # Test proposal generation
    res = ShopperAgent.generate_proposal(prompt, policy)
    assert res["proposal"] is not None
    assert res["proposal"].total_amount > 0
    assert res["recommendation_explanation"] is not None
    assert len(res["recommendation_explanation"]) > 10


@pytest.mark.asyncio
async def test_ollama_status_endpoint():
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/agent/model-status")
        assert response.status_code == 200
        data = response.json()
        assert "available" in data
        assert data["model"] == "qwen2.5-coder:7b"
