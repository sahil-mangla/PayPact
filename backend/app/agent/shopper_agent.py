import re
import uuid
from typing import Dict, Any, Optional

from app.agent.requirements import (
    ProductFacts,
    parse_requirements,
    city_name,
    shares_topic,
    topic_overlap,
    unmet_requirements,
    verified_facts,
)
from app.catalogue.products import (
    CATALOGUE,
    Product,
    get_product_by_sku,
    search_catalogue,
)
from app.fingerprint.canonical import compute_proposal_fingerprint
from app.models.schemas import (
    AgentQuota,
    AuthorizationPolicy,
    LineItem,
    PurchaseProposal,
)


class NoMatchingProductError(ValueError):
    """No catalogue item satisfies the explicit requirements in the request.

    `details` (set when the catalogue was searched) carries what was asked for and the
    nearest item, so a client can show a structured result instead of only the message.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details


class ShopperAgent:
    """AI Purchasing Agent.

    Translates user purchase requests into structured recommendations and candidate proposals.
    Strictly isolated: has ZERO payment execution authority and ZERO access to payment tokens.
    """

    @staticmethod
    def _facts(product: Product) -> ProductFacts:
        return ProductFacts(
            sku=product.sku,
            kind=product.kind,
            origin=product.origin,
            destination=product.destination,
            travel_class=product.travel_class,
            trip_type=product.trip_type,
            airline=product.airline,
        )

    @classmethod
    def _closest(cls, requirements, user_prompt: str, ranked):
        """The (unmet reasons, item) pair nearest to the request, or None for no candidates.

        Best first: fewest unmet requirements, then an item of the kind asked for, then
        more topic words shared with the prompt (name, category and kind only: descriptions
        are merchant-written, so they never count), then real items before the catalogue's
        test fixtures, then the lower price, then the sku.
        """
        scored = [(unmet_requirements(requirements, cls._facts(p)), p) for p in ranked]
        if not scored:
            return None

        def nearness(entry):
            reasons, p = entry
            return (
                len(reasons),
                0 if p.kind in requirements.kinds else 1,
                -topic_overlap(user_prompt, f"{p.name} {p.category} {p.kind}"),
                "fixture" in p.name.lower(),  # test-lab items are a last resort to show a user
                p.unit_price * requirements.quantity + p.shipping_fee + p.tax_fee,
                p.sku,
            )

        return min(scored, key=nearness)

    @classmethod
    def _no_match_message(cls, requirements, user_prompt: str, ranked) -> str:
        """Explain why nothing matched, naming the closest item and what it gets wrong."""
        nearest = cls._closest(requirements, user_prompt, ranked)
        if not nearest:
            return "No products found matching purchase intent in catalogue."
        reasons, closest = nearest
        reasons = reasons or ["nothing in the catalogue relates to what you asked for"]
        return (
            "No catalogue item matches this request, so nothing was proposed. "
            f"Closest option: {closest.name} from {closest.merchant}, which does not match "
            f"because {'; '.join(reasons)}."
        )

    @classmethod
    def _no_match_details(cls, requirements, user_prompt: str, ranked) -> Dict[str, Any]:
        """Structured twin of the no-match message: what was asked and the nearest item."""
        requested: Dict[str, Any] = {}
        if len(requirements.kinds) == 1:
            requested["kind"] = next(iter(requirements.kinds))
        if requirements.origin:
            requested["origin"] = city_name(requirements.origin)
        if requirements.destination:
            requested["destination"] = city_name(requirements.destination)
        if requirements.travel_class:
            requested["travel_class"] = requirements.travel_class
        if requirements.quantity > 1:
            requested["quantity"] = requirements.quantity
        if requirements.round_trip:
            requested["round_trip"] = True
        if requirements.airline:
            requested["airline"] = requirements.airline.title()

        nearest = cls._closest(requirements, user_prompt, ranked)
        closest = None
        if nearest:
            reasons, item = nearest
            closest = {
                "sku": item.sku,
                "name": item.name,
                "merchant": item.merchant,
                "unit_price": item.unit_price,
                "currency": item.currency,
                "differences": reasons
                or ["nothing in the catalogue relates to what you asked for"],
            }
        return {"requested": requested, "closest": closest}

    @staticmethod
    def _mentions(text: str, words: list) -> bool:
        """True if any of `words` appears in `text` as a whole word (optionally pluralised).

        Substring matching misread "automatically" as a request for a mat.
        """
        pattern = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")(?:s|es)?\b"
        return re.search(pattern, text.lower()) is not None

    @staticmethod
    def _category_from_prompt(user_prompt: str) -> Optional[str]:
        """Deterministic keyword classification of the purchase category, or None."""
        mentions = ShopperAgent._mentions
        prompt_lower = user_prompt.lower()
        if mentions(
            prompt_lower,
            [
                "flight",
                "hotel",
                "ticket",
                "bangalore",
                "blr",
                "delhi",
                "airline",
                "travel",
                "transit",
            ],
        ):
            return "travel"
        if mentions(
            prompt_lower,
            ["mat", "wrist", "dock", "supplies", "desk", "cable", "organizer", "tray"],
        ):
            return "office supplies"
        if mentions(
            prompt_lower,
            ["keyboard", "switch", "keycap", "keychron", "meckeys", "typing"],
        ):
            return "mechanical keyboard"
        if "mouse pad" in prompt_lower or "mousepad" in prompt_lower:
            return "office supplies"
        if mentions(prompt_lower, ["mouse", "mice"]):
            return "computer mouse"
        if mentions(prompt_lower, ["monitor"]):
            return "computer monitor"
        return None

    @staticmethod
    def _amounts_in_prompt(user_prompt: str) -> list:
        """Every positive amount the user actually typed ("5,000", "₹4000", "5k")."""
        text = user_prompt.lower()
        amounts = []
        for raw, suffix in re.findall(
            r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*(k\b)?", text
        ):
            try:
                val = float(raw.replace(",", ""))
            except ValueError:
                continue
            if suffix:
                val *= 1000
            if val > 0:
                amounts.append(round(val, 2))
        return amounts

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

        # 1. Attempt cloud Gemini or local Ollama inference
        llm_data = None
        try:
            from app.agent.gemini_client import GeminiClient

            llm_data = GeminiClient.parse_intent(user_prompt)
        except Exception:
            llm_data = None

        if not llm_data:
            try:
                from app.agent.ollama_client import OllamaClient

                llm_data = OllamaClient.parse_intent(user_prompt)
            except Exception:
                llm_data = None

        if llm_data and isinstance(llm_data, dict):
            if "category" in llm_data and llm_data["category"]:
                cat_str = str(llm_data["category"]).lower()
                if cls._mentions(
                    cat_str, ["flight", "travel", "hotel", "airline", "ticket"]
                ):
                    category = "travel"
                elif cls._mentions(
                    cat_str, ["mat", "dock", "supplies", "desk", "organizer", "wrist"]
                ):
                    category = "office supplies"
                elif "keyboard" in cat_str:
                    category = "mechanical keyboard"
                elif "mouse" in cat_str:
                    category = "computer mouse"
                elif "monitor" in cat_str:
                    category = "computer monitor"
                else:
                    # An unrecognised label (e.g. "computer accessories") must not
                    # override what the prompt plainly says
                    category = cls._category_from_prompt(user_prompt) or cat_str
            # The budget is spending authority, so the model may only restate a number the
            # user actually typed. Anything else it produces is ignored, not trusted.
            typed = set(cls._amounts_in_prompt(user_prompt))
            heuristic = sorted(typed)
            if len(heuristic) >= 2:
                auto_limit, max_total = heuristic[-2], heuristic[-1]
            elif len(heuristic) == 1:
                max_total = heuristic[0]
                auto_limit = round(max_total * 0.8, 2)

            if "max_budget" in llm_data and isinstance(
                llm_data["max_budget"], (int, float)
            ):
                parsed_max = round(float(llm_data["max_budget"]), 2)
                if parsed_max > 0 and parsed_max in typed:
                    max_total = parsed_max
                    auto_limit = round(max_total * 0.8, 2)
            if "auto_buy_limit" in llm_data and isinstance(
                llm_data["auto_buy_limit"], (int, float)
            ):
                parsed_auto = round(float(llm_data["auto_buy_limit"]), 2)
                if parsed_auto > 0 and parsed_auto in typed:
                    auto_limit = min(parsed_auto, max_total)
            if "currency" in llm_data and str(llm_data["currency"]).upper() in [
                "INR",
                "USD",
            ]:
                currency = str(llm_data["currency"]).upper()
        else:
            # 2. Resilient heuristic fallback
            prompt_lower = user_prompt.lower()

            # Extract currency
            if "$" in user_prompt or "usd" in prompt_lower:
                currency = "USD"
            elif "₹" in user_prompt or "inr" in prompt_lower or "rs" in prompt_lower:
                currency = "INR"

            # Extract numerical limits (budget and auto-threshold)
            clean_nums = cls._amounts_in_prompt(user_prompt)

            if len(clean_nums) >= 2:
                s = sorted(clean_nums)
                auto_limit = s[-2]
                max_total = s[-1]
            elif len(clean_nums) == 1:
                max_total = clean_nums[0]
                auto_limit = round(max_total * 0.8, 2)

            # Detect category
            category = cls._category_from_prompt(user_prompt) or category

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

    # Amounts that carry a currency marker, e.g. "₹14,500", "$20", "5000 INR".
    _MONEY_RE = re.compile(
        r"(?:₹|\$|rs\.?|inr|usd)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:inr|usd|rupees|dollars)",
        re.IGNORECASE,
    )
    _SKU_LIKE_RE = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+){1,}\b")

    @classmethod
    def _cites_unknown_figures(
        cls,
        text: str,
        product: Product,
        proposal: PurchaseProposal,
        policy: AuthorizationPolicy,
    ) -> bool:
        """True if free text names a price or SKU that is not part of this proposal.

        Merchant descriptions and model output are untrusted. An explanation shown as the
        agent's reasoning must not smuggle in figures ("pre-approved upgrade to SKU-X at
        ₹14,500") that the verified proposal does not contain.
        """
        allowed = {
            round(v, 2)
            for v in (
                product.unit_price,
                proposal.item_subtotal,
                proposal.shipping_fee,
                proposal.tax_fee,
                proposal.total_amount,
                policy.maximum_total,
                policy.automatic_purchase_limit,
                policy.maximum_total - policy.spent_total,
            )
        }
        for match in cls._MONEY_RE.finditer(text):
            raw = (match.group(1) or match.group(2)).replace(",", "").rstrip(".")
            try:
                if round(float(raw), 2) not in allowed:
                    return True
            except ValueError:
                return True
        known_skus = {product.sku.upper()}
        return any(
            token.upper() not in known_skus and token.upper() != "SKU"
            for token in cls._SKU_LIKE_RE.findall(text)
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
        preferred_cat = (
            agent_category_map.get(agent_id or "") or policy.product_category
        )

        requirements = parse_requirements(user_prompt)
        agent_choice = None
        agent_trace: list = []

        if not target_product:
            ranked = search_catalogue(
                user_prompt, category_filter=preferred_cat, max_results=len(CATALOGUE)
            )
            # Only items that satisfy what the request explicitly asks for may be proposed
            candidates = [
                c
                for c in ranked
                if not unmet_requirements(requirements, cls._facts(c))
                # No recognisable product type: the prompt must at least name something
                # the item is about, or "buy me a yacht" would get a keyboard. Descriptions
                # are merchant-written free text, so they never count as a match.
                and (
                    requirements.kinds
                    or shares_topic(user_prompt, f"{c.name} {c.category} {c.kind}")
                )
            ]

            # Let the model choose first. Its pick only counts if it is one of the genuine
            # matches above, so it cannot pick something the request or persona rules out.
            from app.agent.tool_agent import choose_product

            picked = choose_product(user_prompt, policy)
            if picked:
                agent_trace = list(picked.trace)
                match = next((c for c in candidates if c.sku == picked.sku), None)
                if match:
                    target_product, agent_choice = match, picked
                else:
                    agent_trace.append(
                        {
                            "tool": "verifier",
                            "args": {"sku": picked.sku},
                            "summary": "Rejected: does not satisfy the request, so the deterministic search decides.",
                        }
                    )

            if not target_product:
                # Among genuine matches, prefer ones that fit the authorised budget; if none
                # do, keep the ranking so the policy engine shows the rejection
                def total(c: Product) -> float:
                    return c.unit_price * requirements.quantity + c.shipping_fee + c.tax_fee

                within = [c for c in candidates if total(c) <= policy.maximum_total]
                candidates = within or candidates
                # Find best candidate within target category
                for cand in candidates:
                    if preferred_cat and (
                        preferred_cat.lower() in cand.category.lower()
                        or cand.category.lower() in preferred_cat.lower()
                    ):
                        target_product = cand
                        break
                if not target_product and candidates:
                    target_product = candidates[0]

            if not target_product:
                raise NoMatchingProductError(
                    cls._no_match_message(requirements, user_prompt, ranked),
                    details=cls._no_match_details(requirements, user_prompt, ranked),
                )

        # Catalogue prices are in the product's own currency, and the policy limits are in the
        # currency the user stated. Comparing across the two would mislabel the charge, so
        # refuse and say why instead of guessing a conversion.
        budget_currency = (
            policy.allowed_currencies[0] if policy.allowed_currencies else "INR"
        ).upper()
        if target_product.currency.upper() != budget_currency:
            raise NoMatchingProductError(
                f"'{target_product.name}' is priced in {target_product.currency.upper()}, but "
                f"your budget is in {budget_currency}. State your budget in "
                f"{target_product.currency.upper()} so the limits apply to the real price."
            )

        # Build LineItem
        line_item = LineItem(
            sku=target_product.sku,
            name=target_product.name,
            quantity=requirements.quantity,
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
            currency=target_product.currency.upper(),
        )

        # Attach computed canonical fingerprint
        proposal.proposal_fingerprint = compute_proposal_fingerprint(proposal)

        facts = verified_facts(requirements, cls._facts(target_product))

        # Generate contextual recommendation rationale via cloud Gemini or local Ollama
        explanation: str
        rationale: Optional[str] = None
        source_tag: str = ""

        if agent_choice and agent_choice.reason:
            rationale = agent_choice.reason
            source_tag = "[Chosen by Gemini 2.5 Flash via tool calls]"

        if not rationale:  # the tool call may already have carried one
            try:
                from app.agent.gemini_client import GeminiClient

                rationale = GeminiClient.generate_recommendation_rationale(
                    user_prompt=user_prompt,
                    product_name=target_product.name,
                    product_merchant=target_product.merchant,
                    unit_price=target_product.unit_price,
                    currency=proposal.currency,
                    product_desc=target_product.description,
                    verified_facts=facts,
                    quantity=requirements.quantity,
                )
                if rationale:
                    source_tag = "[Powered by Gemini 2.5 Flash]"
            except Exception:
                rationale = None

        if not rationale:
            try:
                from app.agent.ollama_client import OllamaClient

                rationale = OllamaClient.generate_recommendation_rationale(
                    user_prompt=user_prompt,
                    product_name=target_product.name,
                    product_merchant=target_product.merchant,
                    unit_price=target_product.unit_price,
                    currency=proposal.currency,
                    product_desc=target_product.description,
                    verified_facts=facts,
                    quantity=requirements.quantity,
                )
                if rationale:
                    source_tag = "[Inferred locally via Ollama qwen2.5-coder:7b]"
            except Exception:
                rationale = None

        if rationale and cls._cites_unknown_figures(
            rationale, target_product, proposal, policy
        ):
            rationale = None
            source_tag = ""

        if rationale:
            r_clean = rationale.strip()
            # Double check for dangling conjunctions or cut-offs
            words = r_clean.split()
            last_word = words[-1].lower().strip(".,;:?!\"'") if words else ""
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
            }
            if last_word in dangling:
                r_clean = (
                    r_clean.rstrip(" ,;:-")
                    + f" delivers dependable performance while strictly satisfying your spending limits at {target_product.unit_price:.0f} {proposal.currency}."
                )
            elif not r_clean.endswith((".", "!", "?", '"', "'")):
                r_clean += "."

            explanation = f"{r_clean} {source_tag}".strip()
        else:
            explanation = (
                f"I recommend the '{target_product.name}' from {target_product.merchant}. "
                f"Unit price is {target_product.unit_price:.2f} {proposal.currency}. "
            )
            if not cls._cites_unknown_figures(
                target_product.description, target_product, proposal, policy
            ):
                explanation += target_product.description
            else:
                explanation += (
                    "The listing text was omitted because it names prices or items "
                    "that are not part of this proposal."
                )
            if facts:
                explanation += f" Checked against your request: {'; '.join(facts)}."

        return {
            "recommendation_explanation": explanation,
            "proposal": proposal,
            "product": target_product,
            "agent_mode": "gemini_tools" if agent_choice else "deterministic",
            "agent_trace": agent_trace,
        }
