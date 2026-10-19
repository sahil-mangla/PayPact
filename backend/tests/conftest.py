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
