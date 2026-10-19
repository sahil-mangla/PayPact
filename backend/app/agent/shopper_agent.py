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
        Uses deterministic heuristic extraction with support for ₹, $, INR, USD.
        """
        prompt_lower = user_prompt.lower()

        # Extract currency
        currency = "INR"
        if "$" in user_prompt or "usd" in prompt_lower:
            currency = "USD"
        elif "₹" in user_prompt or "inr" in prompt_lower or "rs" in prompt_lower:
            currency = "INR"

        # Extract numerical limits (budget and auto-threshold)
        numbers = re.findall(r"(?:₹|\$|rs\.?|inr)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+)", prompt_lower)
        clean_nums = []
        for n in numbers:
            try:
                clean_nums.append(float(n.replace(",", "")))
            except ValueError:
                continue

        # Sensible defaults if not specified
        max_total = 5000.00
        auto_limit = 4000.00

        if len(clean_nums) >= 2:
            # Usually highest is max budget, lower is auto limit
            s = sorted(clean_nums)
            auto_limit = s[-2]
            max_total = s[-1]
        elif len(clean_nums) == 1:
            max_total = clean_nums[0]
            auto_limit = round(max_total * 0.8, 2)

        # Detect category
        category = "mechanical keyboard"
        if "keyboard" in prompt_lower:
            category = "mechanical keyboard"
        elif "mouse" in prompt_lower:
            category = "computer mouse"
        elif "monitor" in prompt_lower:
            category = "computer monitor"

        # Default Swarm Hierarchy Allocation across specialized agent personas
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

        return AuthorizationPolicy(
            policy_id=f"pol_{uuid.uuid4().hex[:8]}",
            version=1,
            user_id=user_id,
            product_category=category,
            maximum_total=max_total,
            spent_total=0.0,
            automatic_purchase_limit=auto_limit,
            allowed_currencies=[currency, "USD" if currency == "INR" else "INR"],
            allowed_merchants=["Keychron India", "Meckeys"],
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

        if not target_product:
            candidates = search_catalogue(user_prompt)
            # Find best candidate within category
            for cand in candidates:
                if policy.product_category and policy.product_category.lower() in cand.category.lower():
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

        return {
            "recommendation_explanation": (
                f"I recommend the '{target_product.name}' from {target_product.merchant}. "
                f"Unit price is {target_product.unit_price:.2f} {proposal.currency}. "
                f"{target_product.description}"
            ),
            "proposal": proposal,
            "product": target_product,
        }
