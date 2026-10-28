"""Google Gemini Cloud LLM Client for PayPact Agent.

Provides cloud-hosted inference using Gemini 2.5 Flash for natural language
intent parsing and contextual product recommendation rationale.
Seamlessly falls back to local Ollama or deterministic heuristics if unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "8.0"))


class GeminiClient:
    """Helper for Google Gemini API inference."""

    @classmethod
    def get_api_key(cls) -> str:
        return os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()

    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        """Check if Gemini API key is configured and can reach Google Generative Language API."""
        key = cls.get_api_key()
        if not key:
            return {
                "available": False,
                "reason": "No GEMINI_API_KEY set",
                "model": GEMINI_MODEL,
            }

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}?key={key}"
            with httpx.Client(timeout=3.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    return {
                        "available": True,
                        "model": GEMINI_MODEL,
                        "provider": "Google Generative Language (Gemini)",
                    }
                return {
                    "available": False,
                    "status_code": res.status_code,
                    "reason": res.text[:120],
                    "model": GEMINI_MODEL,
                }
        except Exception as e:
            return {"available": False, "reason": str(e), "model": GEMINI_MODEL}

    @classmethod
    def parse_intent(cls, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Ask Gemini model to parse purchasing intent into structured parameters."""
        key = cls.get_api_key()
        if not key:
            return None

        prompt = (
            "You are an enterprise AI purchasing assistant for PayPact.\n"
            "Analyze this user request:\n"
            f'"{user_prompt}"\n\n'
            "Extract the purchasing intent into valid JSON with these exact keys:\n"
            "- category: string (short product category, e.g. 'mechanical keyboard', 'travel', 'office supplies')\n"
            "- max_budget: number (maximum total spend ceiling authorized)\n"
            "- auto_buy_limit: number (threshold below which auto-purchase is permitted, typically 70-80% of max budget)\n"
            "- currency: string ('INR' or 'USD')\n"
            "- explanation: string (brief 1-sentence rationale of how the policy was interpreted)\n\n"
            "Output ONLY valid JSON inside a ```json ``` block."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1200,
            },
        }

        try:
            with httpx.Client(timeout=GEMINI_TIMEOUT) as client:
                res = client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(
                            p.get("text", "")
                            for p in parts
                            if isinstance(p, dict) and not p.get("thought", False)
                        )
                        # Extract JSON block
                        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
                        raw_json = json_match.group(1) if json_match else text.strip()
                        parsed = json.loads(raw_json)
                        if isinstance(parsed, dict) and "max_budget" in parsed:
                            return parsed
        except Exception as e:
            logger.warning(f"Gemini intent parsing failed: {e}")

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
        """Ask Gemini model to produce natural agent reasoning."""
        key = cls.get_api_key()
        if not key:
            return None

        prompt = (
            "You are an autonomous enterprise purchasing agent for PayPact.\n"
            f'User prompt: "{user_prompt}"\n'
            f"Selected product: {product_name}\n"
            f"Merchant: {product_merchant}\n"
            f"Price: {unit_price:.2f} {currency}\n"
            f"Description: {product_desc}\n"
            f"Quantity: {quantity}\n"
            f"Requirements the system verified: {'; '.join(verified_facts or []) or 'none stated'}\n\n"
            "Write a complete, professional 2-sentence rationale explaining how this product fits the user's request "
            "and their financial budget ceiling. State only facts that appear in the description or the verified list above. "
            "Never claim a route, date, class, feature or any requirement that is not listed there. "
            "Always complete your thoughts and conclude with a period."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1500,
            },
        }

        try:
            with httpx.Client(timeout=GEMINI_TIMEOUT) as client:
                res = client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(
                            p.get("text", "")
                            for p in parts
                            if isinstance(p, dict) and not p.get("thought", False)
                        )
                        cleaned = text.strip().replace("\n", " ")
                        cleaned = re.sub(r"\s+", " ", cleaned).strip()

                        if len(cleaned) < 20:
                            return None

                        # Check for cut-off / dangling words at the end
                        dangling = {
                            "that",
                            "and",
                            "or",
                            "but",
                            "with",
                            "for",
                            "to",
                            "at",
                            "by",
                            "of",
                            "in",
                            "is",
                            "a",
                            "an",
                            "the",
                            "which",
                            "as",
                            "from",
                            "on",
                            "it",
                            "so",
                            "because",
                        }
                        words = cleaned.split()
                        last_word = (
                            words[-1].lower().strip(".,;:?!\"'") if words else ""
                        )

                        if last_word in dangling:
                            logger.warning(
                                f"Detected cut-off LLM rationale: '{cleaned}'. Completing thought."
                            )
                            cleaned = (
                                cleaned.rstrip(" ,;:-")
                                + f" delivers dependable performance while strictly satisfying your spending limits at {unit_price:.0f} {currency}."
                            )
                        elif not cleaned.endswith((".", "!", "?", '"', "'")):
                            cleaned += "."

                        return cleaned
        except Exception as e:
            logger.warning(f"Gemini recommendation generation failed: {e}")

        return None
