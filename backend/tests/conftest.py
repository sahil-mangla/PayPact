"""Pytest configuration and test isolation fixtures."""

import pytest
from app.api.routers import coordinator


@pytest.fixture(autouse=True)
def mock_paypal_for_tests():
    """Ensure automated test suite runs in mock mode without external network dependencies."""
    prev_mode = coordinator.paypal_client.mock_mode
    coordinator.paypal_client.mock_mode = True
    yield
    coordinator.paypal_client.mock_mode = prev_mode


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    """Keep the suite hermetic: no test may depend on a local Ollama model or a Gemini key.

    Live model output is non-deterministic (the same prompt was labelled both
    "office supplies" and "computer accessories"), so tests that exercise the agent run
    on the deterministic parser. Tests that need an LLM response mock the client.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr("app.agent.ollama_client.OLLAMA_BASE_URL", "http://127.0.0.1:9")


@pytest.fixture(autouse=True)
def fresh_model_health_cache():
    """Health results are cached for a short window; every test starts without one."""
    from app.api import routers

    routers.reset_model_health_cache()
    yield
