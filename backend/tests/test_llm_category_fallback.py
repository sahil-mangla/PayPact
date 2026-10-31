from unittest.mock import patch

import pytest

from app.agent.gemini_client import GeminiClient
from app.agent.ollama_client import OllamaClient
from app.agent.shopper_agent import ShopperAgent

DESK_MAT_PROMPT = "Order custom brass keyboard desk mat under ₹2,000."


def llm_answer(category: str):
    return {
        "category": category,
        "max_budget": 2000,
        "auto_buy_limit": 1600,
        "currency": "INR",
    }


@pytest.mark.parametrize(
    "llm_label", ["computer accessories", "peripherals", "gadgets", "desk accessory"]
)
def test_unrecognised_llm_label_defers_to_prompt_keywords(llm_label):
    """The LLM's label must not override what the prompt plainly says."""
    with patch.object(OllamaClient, "parse_intent", return_value=llm_answer(llm_label)):
        policy = ShopperAgent.parse_intent_to_policy(DESK_MAT_PROMPT)

    assert policy.product_category == "office supplies"
    assert policy.agent_quotas["agent_supplies"].allocated_budget == 2000.0


def test_llm_label_with_no_prompt_keyword_is_kept():
    """With nothing in the prompt to classify by, the LLM's own label stands."""
    with patch.object(
        OllamaClient, "parse_intent", return_value=llm_answer("garden furniture")
    ):
        policy = ShopperAgent.parse_intent_to_policy("Buy a bench under ₹2,000.")

    assert policy.product_category == "garden furniture"


def test_known_llm_label_is_normalised():
    with patch.object(
        GeminiClient, "parse_intent", return_value=llm_answer("flight booking")
    ):
        policy = ShopperAgent.parse_intent_to_policy("Book something under ₹2,000.")

    assert policy.product_category == "travel"


def test_suite_never_reaches_a_live_llm():
    """Guards the isolation fixture: with it active the LLM clients report unavailable."""
    assert OllamaClient.check_health()["available"] is False
    assert GeminiClient.check_health()["available"] is False
