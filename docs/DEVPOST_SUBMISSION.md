# Devpost Submission — Agent Payment Integrity Layer (APIL)

## 📌 Project Overview

- **Project Title:** APIL — Agent Payment Integrity Layer
- **Tagline:** Deterministic Cryptographic Guardrails, Multi-Agent Swarm Budget Trees & Pre-Execution Verification for Autonomous AI Agents Transacting via PayPal
- **Hackathon Track:** PayPal AI Hackathon — Safe & Agentic Commerce
- **Video Deliverable:** `brag-output/brag.mp4` (20-second 1080p high-impact launch video) & `brag-output/brag.jpg` (Poster frame)
- **Repository:** [github.com/sahilmangla/paypal-hack](https://github.com/sahilmangla/paypal-hack)

---

## 💡 Inspiration

Autonomous AI shopping agents are rapidly moving from novelty to everyday enterprise reality. However, granting language models direct authority to execute real-world financial transactions presents catastrophic failure modes:

1. **Hallucination & Math Drift:** LLMs produce non-deterministic outputs and frequently err on arithmetic (taxes, fees, quantities).
2. **Checkout Price Drift (Dark Patterns):** Merchants often add hidden fees or change prices between item selection and final order capture.
3. **Product Substitution / Phishing:** In flight, items can be silently substituted for inferior or counterfeit SKUs.
4. **Prompt Injection & Overruling:** Adversarial instructions embedded in merchant web pages or product descriptions can trick an LLM agent into bypassing spending limits.
5. **Double-Spend & Race Conditions:** Asynchronous agent retries or parallel workers can lead to duplicate PayPal order authorizations.
6. **Multi-Agent Swarm Overspend:** Multiple autonomous sub-agents (e.g. hardware agent, travel agent, supplies agent) sharing a project budget can simultaneously deplete funds without centralized atomic coordination.

Directly connecting an LLM to a payment gateway API without verifiable guardrails is fundamentally unsafe. We built **APIL** to solve this: a zero-trust, deterministic cryptographic integrity layer that sits between autonomous agents and PayPal.

---

## 🛡️ What It Does

**APIL (Agent Payment Integrity Layer)** acts as an immutable firewall between AI agents and PayPal's payment gateways. It guarantees that **no payment can ever be captured unless it strictly adheres to a user-authorized policy, satisfies multi-agent swarm quotas, and matches its cryptographically approved proposal fingerprint.**

### Core Capabilities:
1. **Natural Language Intent Compilation:** The shopper defines policies in plain English (e.g., *"Find a wireless mechanical keyboard under ₹5,000, auto-buy if under ₹4,000"*), which are compiled into strict, schema-validated Pydantic policies.
2. **Canonical Proposal Fingerprinting:** Proposals are hashed using deterministic SHA-256 over sorted line items, normalized currencies, and rounded values. Any modification—even by 1 cent—alters the fingerprint.
3. **Deterministic Pre-Execution Invariant Gate:** Milliseconds before contacting PayPal, APIL re-evaluates all policy constraints and checks the cryptographic fingerprint against the approved proposal state. If drift or tampering is detected, **the payment is blocked immediately before PayPal is ever contacted.**
4. **Hierarchical Swarm Budget Trees:** Supports multi-agent teams (`agent_hardware`, `agent_travel`, `agent_supplies`) governed under a master project budget ceiling. Each agent possesses a dedicated non-fungible quota with real-time atomic dual-decrementing.
5. **Digitally Signed Cryptographic Audit Receipts (HMAC-SHA256):** Every completed transaction, rejection, or dispute exports a verifiable `SignedAuditReceipt` binding policy version, proposal fingerprint, and PayPal telemetry. Verifiable via `POST /api/receipt/verify`.
6. **Asynchronous Webhook Reconciliation Engine:** Production listener (`POST /api/webhooks/paypal`) and local testbed simulator (`POST /api/webhooks/simulate`) for handling `PAYMENT.CAPTURE.REFUNDED` and `CUSTOMER.DISPUTE.CREATED` events with automatic quota restoration.
7. **Live PayPal Sandbox Integration:** Supports the official PayPal JS SDK button with a two-phase approval flow (`createOrder` → buyer approval → `onApprove` capture) and atomic transaction locking to eliminate double-spend.
8. **Tamper-Evident Hash-Chained Audit Ledger:** Every state transition and policy decision is recorded in an append-only cryptographic ledger (`SHA-256(index + prev_hash + data)`), providing undeniable auditability for chargebacks or security audits.
9. **Empirical Integrity Lab & Benchmark Matrix:** Evaluates 7 adversarial scenarios (nominal path, price drift, revoked policy, SKU substitution, duplicate submission, prompt injection, and timeout reconciliation) across 3 system paradigms:
   - *Baseline A (Direct LLM):* **14.3%** pass rate
   - *Baseline B (Static Limits):* **57.1%** pass rate
   - *Proposed APIL:* **100%** pass rate (7/7 blocked or safely cleared)

---

## 🏗️ How We Built It

- **Deterministic Backend:** Built with **Python 3.13** and **FastAPI**, employing **Pydantic v2** for strict schema validation, **pytest** with **53 automated tests** covering edge cases, floating point rounding, swarm quotas, and concurrency locking.
- **PayPal Integration:** Live PayPal v2 Orders REST API integration with OAuth2 client-credentials authentication, idempotency headers (`PayPal-Request-Id`), and dynamic currency adaptation for global sandboxes.
- **Frontend Dashboard:** Built with **Next.js 14**, **React 18**, and **Vanilla CSS** with a dark glassmorphic design system. Features real-time agent thinking animation, interactive visual drift injection, live PayPal Buttons (`@paypal/react-paypal-js`), multi-agent persona selector, signed receipt downloader, and persistent benchmark analytics.
- **Cryptographic Engine:** SHA-256 canonical JSON serialization (RFC 8785 principles) with sorted keys and normalized whitespace to ensure identical proposals always yield identical fingerprints across different runtimes, alongside HMAC-SHA256 constant-time signature verification.

---

## ⚡ Challenges We Ran Into & Solutions

1. **PayPal Sandbox REST Currency Requirements:** PayPal's REST Orders API v2 restricts currency codes for standard accounts (e.g. INR is not supported for global REST orders). We implemented seamless currency normalization and arithmetic balance protection (`breakdown.item_total + shipping + tax == amount.value`) to allow international policy definitions while ensuring PayPal Sandbox orders execute with 100% fidelity.
2. **Sub-Cent Floating Point Rounding:** Currency math in standard IEEE 754 floats introduces rounding anomalies (e.g. `0.1 + 0.2 != 0.3`). We enforced strict decimal quantizing and canonical rounding across all policy evaluation rules.
3. **Concurrency & Double-Spend:** When agents experience network timeouts or launch parallel workers, duplicate payments can occur. We engineered checkout-level `asyncio.Lock` state serialization and deterministic idempotency keys, preventing duplicate captures.
4. **Multi-Agent Cross-Depletion:** Parallel sub-agents running asynchronously can deplete shared funds before prior transactions settle. We built hierarchical budget trees where each agent persona receives non-fungible quotas with atomic dual-decrementing against the master budget ceiling.
5. **Bridging LLM Probabilities to Financial Determinism:** LLMs are inherently probabilistic, but payments must be strictly deterministic. We strictly separated concerns: the LLM suggests proposals, but all gatekeeping, policy verification, and checkout execution are executed by a provably deterministic state machine.

---

## 🏆 Accomplishments We're Proud Of

- **100% Benchmark Score:** APIL achieved a perfect 7/7 benchmark score, completely neutralizing price drift, prompt injection, and concurrency races that compromised baseline systems.
- **Multi-Agent Swarm Governance:** Successfully implemented isolated quota tracking and cross-agent risk containment for agent swarms.
- **Exportable HMAC-SHA256 Signed Receipts:** Generated portable, verifiable receipts for chargeback and dispute resolution.
- **End-to-End Live PayPal Checkout:** Successfully verified real PayPal Sandbox order creation and token authorization alongside an offline mock mode for instant automated testing.
- **Zero Drift Escapes:** Zero unauthorized transactions can bypass the pre-execution invariant gate.
- **High Test Coverage:** 53 comprehensive automated tests running in under 0.05 seconds, covering mathematical edge cases, tamper detection in the audit ledger, and policy version invalidations.

---

## 📖 What We Learned

- Financial agents cannot rely on LLM prompts for enforcement; safety must be architectural and deterministic.
- Cryptographic hashing of proposals provides an elegant, zero-overhead mechanism to verify that what the user approved is byte-for-byte what gets paid.
- Pre-execution validation right at the gateway boundary is the most effective defense against dynamic checkout price changes and dark patterns.
- Multi-agent commerce demands hierarchical budget trees with atomic spend decrementing to prevent silent cross-agent fund exhaustion.

---

## 🚀 What's Next for APIL

- **PayPal Braintree & Vault Integration:** Native support for stored payment methods and recurring subscription integrity.
- **Decentralized Audit Export:** Optional anchoring of audit ledger root hashes to public timestamping services for independent multi-party dispute resolution.
- **Mobile SDK & Browser Extension:** Drop-in APIL middleware for Chrome extensions and mobile shopping assistants.
- **Python / Node.js SDK:** Release `pip install apil-firewall` for direct integration into LangChain, CrewAI, AutoGen, and OpenAI Swarm workflows.
