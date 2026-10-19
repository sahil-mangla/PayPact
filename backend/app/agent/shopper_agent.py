import re
import uuid
from typing import Dict, Any, Optional

from app.catalogue.products import Product, get_product_by_sku, search_catalogue
from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    AgentQuota,
    AuthorizationPolicy,
    LineItem,
    PurchaseProposal,
)


class ShopperAgent:
    """AI Purchasing Agent.
    
    Translates user purchase requests into structured recommendations and candidate proposals.
    Strictly isolated: has ZERO payment execution authority and ZERO access to payment tokens.
    """

    @classmethod
    def parse_intent_to_policy(
        cls,
        user_prompt: str,
        user_id: str = "usr_demo",
    ) -> AuthorizationPolicy:
        """Parse natural language request into confirmed policy draft.
        
        Extracts budget limits, currency, and product categories.
        Attempts local Ollama LLM extraction first (e.g. qwen2.5-coder:7b),
        with seamless deterministic fallback.
        """
        category = "mechanical keyboard"
        max_total = 5000.00
        auto_limit = 4000.00
        currency = "INR"

        # 1. Attempt local Ollama inference
        try:
            from app.agent.ollama_client import OllamaClient
            ollama_data = OllamaClient.parse_intent(user_prompt)
        except Exception:
            ollama_data = None

        if ollama_data and isinstance(ollama_data, dict):
            if "category" in ollama_data and ollama_data["category"]:
                cat_str = str(ollama_data["category"]).lower()
                if any(k in cat_str for k in ["flight", "travel", "hotel", "airline", "ticket"]):
                    category = "travel"
                elif any(k in cat_str for k in ["mat", "dock", "supplies", "desk", "organizer", "wrist"]):
                    category = "office supplies"
                elif "keyboard" in cat_str:
                    category = "mechanical keyboard"
                elif "mouse" in cat_str:
                    category = "computer mouse"
                elif "monitor" in cat_str:
                    category = "computer monitor"
                else:
                    category = cat_str
            if "max_budget" in ollama_data and isinstance(ollama_data["max_budget"], (int, float)):
                parsed_max = float(ollama_data["max_budget"])
                if parsed_max > 0:
                    max_total = parsed_max
            if "auto_buy_limit" in ollama_data and isinstance(ollama_data["auto_buy_limit"], (int, float)):
                parsed_auto = float(ollama_data["auto_buy_limit"])
                if parsed_auto > 0:
                    auto_limit = min(parsed_auto, max_total)
                else:
                    auto_limit = round(max_total * 0.8, 2)
            else:
                auto_limit = round(max_total * 0.8, 2)
            if "currency" in ollama_data and str(ollama_data["currency"]).upper() in ["INR", "USD"]:
                currency = str(ollama_data["currency"]).upper()
        else:
            # 2. Resilient heuristic fallback
            prompt_lower = user_prompt.lower()

            # Extract currency
            if "$" in user_prompt or "usd" in prompt_lower:
                currency = "USD"
            elif "₹" in user_prompt or "inr" in prompt_lower or "rs" in prompt_lower:
                currency = "INR"

            # Extract numerical limits (budget and auto-threshold)
            raw_matches = re.findall(r"(?:₹|\$|rs\.?|inr)?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)", prompt_lower)
            clean_nums = []
            for n in raw_matches:
                try:
                    val = float(n.replace(",", ""))
                    if val > 0:
                        clean_nums.append(val)
                except ValueError:
                    continue

            if len(clean_nums) >= 2:
                s = sorted(clean_nums)
                auto_limit = s[-2]
                max_total = s[-1]
            elif len(clean_nums) == 1:
                max_total = clean_nums[0]
                auto_limit = round(max_total * 0.8, 2)

            # Detect category
            if any(k in prompt_lower for k in ["flight", "flights", "hotel", "ticket", "tickets", "bangalore", "blr", "delhi", "airline", "travel", "transit"]):
                category = "travel"
            elif any(k in prompt_lower for k in ["mat", "mats", "wrist", "dock", "supplies", "desk", "cable", "organizer", "tray"]):
                category = "office supplies"
            elif any(k in prompt_lower for k in ["keyboard", "keyboards", "switch", "switches", "keycap", "keycaps", "keychron", "meckeys", "typing"]):
                category = "mechanical keyboard"
            elif "mouse" in prompt_lower:
                category = "computer mouse"
            elif "monitor" in prompt_lower:
                category = "computer monitor"

        # Swarm Hierarchy Allocation prioritized for the requested category
        if category == "travel":
            tr_quota = max_total
            hw_quota = round(max_total * 0.50, 2)
            su_quota = round(max_total * 0.30, 2)
        elif category == "office supplies":
            su_quota = max_total
            hw_quota = round(max_total * 0.60, 2)
            tr_quota = round(max_total * 0.40, 2)
        else:
            hw_quota = max_total
            tr_quota = round(max_total * 0.50, 2)
            su_quota = round(max_total * 0.30, 2)

        quotas = {
            "agent_hardware": AgentQuota(
                agent_id="agent_hardware",
                agent_name="Hardware Procurement Agent",
                role="Hardware & Tech Accessories",
                allocated_budget=hw_quota,
                spent_budget=0.0,
            ),
            "agent_travel": AgentQuota(
                agent_id="agent_travel",
                agent_name="Travel & Bookings Agent",
                role="Flights, Hotels & Transit",
                allocated_budget=tr_quota,
                spent_budget=0.0,
            ),
            "agent_supplies": AgentQuota(
                agent_id="agent_supplies",
                agent_name="Office Supplies Agent",
                role="Desk Accessories & Peripherals",
                allocated_budget=su_quota,
                spent_budget=0.0,
            ),
        }

        # Whitelist all verified merchants in our authorized catalogue
        all_merchants = [
            "Keychron India",
            "Meckeys",
            "IndiGo Corporate",
            "Marriott Corporate Portal",
            "DeskSpace Supplies",
        ]

        return AuthorizationPolicy(
            policy_id=f"pol_{uuid.uuid4().hex[:8]}",
            version=1,
            user_id=user_id,
            product_category=category,
            maximum_total=max_total,
            spent_total=0.0,
            automatic_purchase_limit=auto_limit,
            allowed_currencies=[currency, "USD" if currency == "INR" else "INR"],
            allowed_merchants=all_merchants,
            require_approval_above_limit=True,
            is_revoked=False,
            agent_quotas=quotas,
        )

    @classmethod
    def generate_proposal(
        cls,
        user_prompt: str,
        policy: AuthorizationPolicy,
        preferred_sku: Optional[str] = None,
        agent_id: Optional[str] = "agent_hardware",
    ) -> Dict[str, Any]:
        """Propose a product matching user intent within authorized category."""
        target_product: Optional[Product] = None

        if preferred_sku:
            target_product = get_product_by_sku(preferred_sku)

        # Map agent persona to its designated operational domain
        agent_category_map = {
            "agent_travel": "travel",
            "agent_supplies": "office supplies",
            "agent_hardware": "mechanical keyboard",
        }
        preferred_cat = agent_category_map.get(agent_id or "") or policy.product_category

        if not target_product:
            candidates = search_catalogue(user_prompt, category_filter=preferred_cat)
            # Find best candidate within target category
            for cand in candidates:
                if preferred_cat and (preferred_cat.lower() in cand.category.lower() or cand.category.lower() in preferred_cat.lower()):
                    target_product = cand
                    break
            if not target_product and candidates:
                target_product = candidates[0]

        if not target_product:
            raise ValueError("No products found matching purchase intent in catalogue.")

        # Build LineItem
        line_item = LineItem(
            sku=target_product.sku,
            name=target_product.name,
            quantity=1,
            unit_price=target_product.unit_price,
        )

        item_subtotal = round(line_item.quantity * line_item.unit_price, 2)
        shipping_fee = round(target_product.shipping_fee, 2)
        tax_fee = round(target_product.tax_fee, 2)
        total_amount = round(item_subtotal + shipping_fee + tax_fee, 2)

        proposal = PurchaseProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            agent_id=agent_id or "agent_hardware",
            merchant=target_product.merchant,
            items=[line_item],
            item_subtotal=item_subtotal,
            shipping_fee=shipping_fee,
            tax_fee=tax_fee,
            total_amount=total_amount,
            currency=policy.allowed_currencies[0] if policy.allowed_currencies else "INR",
        )

        # Attach computed canonical fingerprint
        proposal.proposal_fingerprint = compute_proposal_fingerprint(proposal)

        # Generate contextual recommendation rationale via local Ollama if available
        explanation: str
        try:
            from app.agent.ollama_client import OllamaClient
            ollama_rationale = OllamaClient.generate_recommendation_rationale(
                user_prompt=user_prompt,
                product_name=target_product.name,
                product_merchant=target_product.merchant,
                unit_price=target_product.unit_price,
                currency=proposal.currency,
                product_desc=target_product.description,
            )
            if ollama_rationale:
                explanation = f"{ollama_rationale} [Inferred locally via Ollama qwen2.5-coder:7b]"
            else:
                explanation = (
                    f"I recommend the '{target_product.name}' from {target_product.merchant}. "
                    f"Unit price is {target_product.unit_price:.2f} {proposal.currency}. "
                    f"{target_product.description}"
                )
        except Exception:
            explanation = (
                f"I recommend the '{target_product.name}' from {target_product.merchant}. "
                f"Unit price is {target_product.unit_price:.2f} {proposal.currency}. "
                f"{target_product.description}"
            )

        return {
            "recommendation_explanation": explanation,
            "proposal": proposal,
            "product": target_product,
        }

