"""Ollama Local LLM Client for APIL Agent.

Provides zero-cloud, 100% local model inference for natural language intent
parsing and contextual product recommendation rationale.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "6.0"))


class OllamaClient:
    """Async & sync helper for local Ollama inference."""

    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        """Check if local Ollama daemon is reachable and model is available."""
        try:
            with httpx.Client(timeout=1.5) as client:
                res = client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    has_model = any(OLLAMA_MODEL in m for m in models)
                    return {
                        "available": True,
                        "model": OLLAMA_MODEL,
                        "installed": has_model,
                        "models_list": models,
                        "base_url": OLLAMA_BASE_URL,
                    }
        except Exception as e:
            logger.debug(f"Ollama health check failed: {e}")
        return {
            "available": False,
            "model": OLLAMA_MODEL,
            "installed": False,
            "models_list": [],
            "base_url": OLLAMA_BASE_URL,
        }

    @classmethod
    def parse_intent(cls, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Ask local Ollama model to parse purchasing intent into structured parameters."""
        prompt = (
            "You are an enterprise AI purchasing assistant. Analyze this user request:\n"
            f'"{user_prompt}"\n\n'
            "Extract the purchasing intent into valid JSON with these exact keys:\n"
            "- category: string (short product category, e.g. 'mechanical keyboard', 'computer mouse', 'travel')\n"
            "- max_budget: number (maximum total spend authorized)\n"
            "- auto_buy_limit: number (threshold below which auto-purchase is allowed, typically 70-80% of max budget)\n"
            "- currency: string ('INR' or 'USD')\n"
            "- explanation: string (brief 1-sentence rationale of how the policy was interpreted)\n"
            "Output ONLY valid JSON."
        )

        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                res = client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                        },
                    },
                )
                if res.status_code == 200:
                    body = res.json()
                    response_text = body.get("response", "{}")
                    parsed = json.loads(response_text)
                    if isinstance(parsed, dict) and "max_budget" in parsed:
                        return parsed
        except Exception as e:
            logger.warning(f"Ollama intent parsing failed or timed out: {e}")
        return None

    @classmethod
    def generate_recommendation_rationale(
        cls,
        user_prompt: str,
        product_name: str,
        product_merchant: str,
        unit_price: float,
        currency: str,
        product_desc: str,
        verified_facts: Optional[List[str]] = None,
        quantity: int = 1,
    ) -> Optional[str]:
        """Ask local Ollama model to produce natural agent reasoning."""
        prompt = (
            f"You are a helpful AI procurement agent. The user wants: '{user_prompt}'.\n"
            f"You selected '{product_name}' priced at {unit_price:.2f} {currency} from '{product_merchant}'.\n"
            f"Product specs: {product_desc}.\n"
            f"Quantity: {quantity}.\n"
            f"Requirements the system verified: {'; '.join(verified_facts or []) or 'none stated'}.\n\n"
            "Write a concise, professional 2-sentence recommendation explaining how this product fits the request and budget. "
            "State only facts that appear in the product specs or the verified list above. Never claim a route, date, class, "
            "feature or any requirement that is not listed there."
        )

        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                res = client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                        },
                    },
                )
                if res.status_code == 200:
                    body = res.json()
                    text = body.get("response", "").strip()
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"Ollama recommendation rationale failed: {e}")
        return None
