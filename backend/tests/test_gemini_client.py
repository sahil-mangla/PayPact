from unittest.mock import patch, MagicMock
from app.agent.gemini_client import GeminiClient


def test_gemini_client_health_check_disabled_when_no_key():
    with patch.object(GeminiClient, "get_api_key", return_value=""):
        res = GeminiClient.check_health()
        assert res["available"] is False
        assert "No GEMINI_API_KEY" in res["reason"]


def test_gemini_client_parse_intent_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": """```json
{
  "category": "mechanical keyboard",
  "max_budget": 5000,
  "auto_buy_limit": 4000,
  "currency": "INR",
  "explanation": "Budget set to INR 5000."
}
```"""
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(GeminiClient, "get_api_key", return_value="fake_key"), patch("httpx.Client.post", return_value=mock_response):
        parsed = GeminiClient.parse_intent("Buy mechanical keyboard under 5000")
        assert parsed is not None
        assert parsed["category"] == "mechanical keyboard"
        assert parsed["max_budget"] == 5000
        assert parsed["auto_buy_limit"] == 4000
        assert parsed["currency"] == "INR"


def test_gemini_client_generate_rationale_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "The Keychron K2 fits the 5000 INR budget and offers tactile switches."
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(GeminiClient, "get_api_key", return_value="fake_key"), patch("httpx.Client.post", return_value=mock_response):
        rationale = GeminiClient.generate_recommendation_rationale(
            user_prompt="Buy mechanical keyboard under 5000",
            product_name="Keychron K2",
            product_merchant="Keychron",
            unit_price=3899.0,
            currency="INR",
            product_desc="Wireless mechanical keyboard",
        )
        assert rationale is not None
        assert "Keychron K2" in rationale
