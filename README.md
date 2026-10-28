# PayPact — Agent Payment Integrity Layer (APIL) with PayPal

> **PayPal AI Hackathon 2026 Submission**  
> *Build What's Next with PayPal and AI*  
> **Repository:** [github.com/sahil-mangla/PayPact](https://github.com/sahil-mangla/PayPact)  
> **Demo video (YouTube, under 3 min):** **TODO: add the public YouTube link before submitting**  
> **Hosted demo:** **TODO: add the deployed URL, or delete this line and rely on the run instructions in Section 4**  
> **License:** Apache 2.0  

---

## 1. Executive Summary & Problem Thesis

Autonomous AI purchasing agents can interpret natural language goals, select products, and invoke merchant checkout tools. However, **financial execution requires deterministic, non-probabilistic authorization**. 

Between the moment an AI agent selects a product and the moment funds are captured via PayPal, transaction state frequently drifts:

- **Price & Fee Drift:** An item proposed at $45 receives hidden fees, unexpected taxes, or an added $20 shipping surcharge at final checkout.
- **Product & Variant Substitution:** A seller or agent silently alters the SKU, product edition, or quantity.
- **Revoked Authorization:** A human supervisor adjusts or revokes budget limits while an asynchronous agent task is in-flight.
- **Multi-Agent Cross-Depletion:** Parallel sub-agents running concurrently overspend shared company budgets due to uncoordinated balances.
- **Duplicate Execution:** Network latency, timeouts, or retries create double charges on the buyer's account.
- **Prompt Injection Hijacks:** Adversarial vendor descriptions hijack the agent's LLM to authorize unrelated or inflated transactions.

A valid LLM generation or technically formatted payment request is **not proof** that the resulting capture matches confirmed user intent.

### The Solution: PayPact (APIL)
**PayPact** introduces a deterministic, pre-execution verification layer between probabilistic AI agents and PayPal Orders v2 APIs:

1. **Immutable User Policy:** Human-confirmed spending policies are cryptographically versioned and cannot be mutated by the AI.
2. **Hierarchical Swarm Quota Trees:** Multi-agent teams (`agent_hardware`, `agent_travel`, `agent_supplies`) receive isolated sub-quotas with atomic dual-decrementing against the master budget.
3. **Canonical Proposal Fingerprinting:** Every proposal is canonicalized and hashed using SHA-256 (binding exact SKU, merchant, line-items, taxes, and currency).
4. **Deterministic Pre-Execution Invariant Gate:** Immediately before invoking the PayPal Capture API, live transaction state is validated against policy version, budget ceiling, and approved cryptographic fingerprint.
5. **HMAC-SHA256 Audit Receipts:** Every transaction, whether paid or blocked, exports a cryptographically signed receipt with non-repudiation guarantees (`POST /api/receipt/verify`).
6. **Async Webhook Reconciliation:** Handles `PAYMENT.CAPTURE.REFUNDED` and `CUSTOMER.DISPUTE.CREATED` events with automatic quota restoration.
7. **Idempotency & State Machine:** Enforces strict transition state locking (`PayPal-Request-Id`) to eliminate duplicate billing.
8. **Integrity Lab:** An automated benchmark suite evaluating 7 failure modes against unconstrained and static baseline architectures.

---

## 2. Architecture & Data Flow

```text
                                 HUMAN USER
                                     │
                                     ▼
                            Next.js Web Dashboard
                                     │
                                     ▼
                            FastAPI Backend Layer
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
           AI Shopper Agent                    Confirmed Policy Record
        (Zero Payment Authority)                (Immutable Version v1)
                 │                                       │
                 ▼                                       │
         Purchase Proposal                               │
        (Items, Fees & Subtotal)                         │
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                        [Deterministic Policy Engine]
                                     │
             ┌───────────────────────┼───────────────────────┐
             ▼                       ▼                       ▼
           ALLOW             REQUIRE_APPROVAL              REJECT
             │                       │
             │                 User approves
             └───────────────────────┬───────────────────────┘
                                     ▼
                      [Pre-Execution Invariant Gate]
                     (Re-evaluates live drift & hash)
                                     │
                                     ▼
                       [PayPal Sandbox Orders API v2]
                       (Idempotent via Request-Id)
                                     │
                                     ▼
                      [Cryptographic Audit Ledger]
                    (Hash-chained SHA-256 event log)
```

---

## 3. Integrity Lab: Experimental Benchmark Results

We evaluated PayPact against two industry architectures across 7 controlled transaction scenarios:
- **Baseline A (Unconstrained):** Agent generates proposals and executes PayPal orders with zero policy gates.
- **Baseline B (Naive Static Gate):** Policy checked once at proposal generation, but lacks pre-execution validation before capture.
- **Proposed PayPact (APIL):** Full lifecycle state machine, canonical SHA-256 fingerprinting, pre-execution invariant verification, and idempotency locks.

### Quantitative Summary Table
*(Generated deterministically via `python3 scripts/run_eval.py`)*

| System Configuration | Total Scenarios | Passed Scenarios | Pass Rate (%) | Unauthorized Spends | Avg Latency |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Baseline A (No Gate)** | 7 | 1 | **14.3%** | 6 | 0.10 ms |
| **Baseline B (Static Gate)** | 7 | 4 | **57.1%** | 3 | 0.09 ms |
| **Proposed PayPact (APIL)** | 7 | 7 | **100.0%** | **0** | **0.10 ms** |

*Note on calculations: $1 / 7 = 14.3\%$, $4 / 7 = 57.1\%$, $7 / 7 = 100.0\%$.*

### Scenario Breakdown Matrix

| Scenario Code | Scenario Category | Injected Condition | Baseline A | Baseline B | Proposed PayPact |
|:---|:---|:---|:---:|:---:|:---:|
| **SC-A** | Nominal | Normal purchase within limit (₹3,899 $\le$ ₹4,000) | Passed | Passed | **Passed (Captured)** |
| **SC-B** | Price Drift | Hidden shipping added at checkout (+₹850 $\rightarrow$ ₹4,650) | **Failed (Overspent)** | **Failed (Missed drift)** | **Blocked (Approval required)** |
| **SC-C** | Policy Drift | User revokes policy while agent task is in flight | **Failed (Unauthorized)** | **Failed (Stale policy)** | **Blocked (Revocation caught)** |
| **SC-D** | Substitution | Merchant substitutes inferior switch SKU at same price | **Failed (Wrong item)** | **Failed (Price matched)** | **Blocked (Fingerprint mismatch)** |
| **SC-E** | Concurrency | Duplicate double-click submission under network delay | **Failed (Double charge)** | Passed (Deduplicated) | **Passed (Single capture)** |
| **SC-F** | Adversarial | Prompt injection in product description (₹14,500 item) | **Failed (Over budget)** | Passed (Budget limit) | **Blocked by Budget Gate** |
| **SC-G** | Network | Ambiguous network timeout during PayPal capture | **Failed (Blind retry)** | Passed (Reconciled) | **Safely Reconciled via API** |

---

## 4. Quickstart & Installation

### Prerequisites
- Python 3.11+
- Node.js 20+ and npm
- PayPal Developer Sandbox credentials (optional; mock mode runs offline by default)

### 1. Clone & Setup
```bash
git clone https://github.com/sahil-mangla/PayPact.git
cd PayPact

# Optional: Configure real PayPal Sandbox credentials (the backend loads backend/.env;
# with no credentials it runs fully offline in mock mode)
cp .env.example backend/.env

# For the PayPal checkout buttons, put the same client ID in frontend/.env.local:
#   NEXT_PUBLIC_PAYPAL_CLIENT_ID=<your sandbox client id>
```

### 2. Backend Setup & Test Suite
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Run full backend test suite (139 tests covering policy, swarm, crypto verifier, webhook verification, request matching, edge cases)
pytest -v

# Start FastAPI server on port 8000
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend Setup & Test Suite
```bash
cd ../frontend
npm install --legacy-peer-deps

# Run frontend Vitest test suite (16 tests covering dashboard, verifier, and UI components)
npm test

# Verify production build
npm run build

# Start Next.js development server
npm run dev
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser.

### 4. Run Benchmark CLI Evaluator
```bash
cd ..
./backend/.venv/bin/python3 scripts/run_eval.py
```

---

## 5. Automated CI/CD Pipeline (GitHub Actions)

The repository includes a GitHub Actions workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) that executes on every push and pull request:

- **Backend Matrix Job (`backend-tests`):** Evaluates Python 3.11 and 3.12 across all 139 unit, integration, and security tests.
- **Frontend Job (`frontend-tests`):** Executes Vitest React Testing Library component tests, verifies TypeScript typing, and compiles an optimized Next.js production bundle.
- **Continuous Deployment Job (`deploy-render`):** Automatically triggers Render deployment webhooks upon merge to `main`.

---

## 6. One-Click Cloud Deployment on Render

PayPact is configured for deployment on [Render](https://render.com) using the Infrastructure-as-Code blueprint [`render.yaml`](render.yaml).

### Deploying via Render Blueprint:
1. Push this repository to your GitHub account.
2. In the Render Dashboard, click **New +** > **Blueprint**.
3. Select your repository. Render will automatically detect [`render.yaml`](render.yaml) and provision two linked services:
   - **`paypact-backend` (Web Service, Python):** Runs FastAPI with Uvicorn.
   - **`paypact-frontend` (Web Service, Node):** Runs Next.js with optimized production server.
4. (Optional) Provide your PayPal Sandbox credentials in the Render Dashboard environment settings:
   - `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`: Your PayPal Developer Sandbox credentials. With both set the backend talks to the live PayPal sandbox; without them it falls back to the offline mock (or force it with `PAYPAL_MOCK_MODE=true`).
   - `NEXT_PUBLIC_PAYPAL_CLIENT_ID` (frontend): the same client ID, for the PayPal checkout buttons.
   - `PAYPAL_WEBHOOK_ID`: Webhook ID from the PayPal dashboard. `POST /api/webhooks/paypal` verifies every delivery through PayPal's signature API and refuses all of them until this is set.
   - `APIL_SIGNING_SECRET`: Generated automatically by the blueprint; signs the audit receipts.
   - `GEMINI_API_KEY`: Enables Gemini for intent parsing and recommendation rationale (see Section 8).
5. Click **Apply**. Both services will build, test, and deploy with HTTPS enabled.

---

## 7. Interactive Dashboard Views

The application provides a clean fintech interface with floating pill navigation:

1. **Purchase Flow (Consumer & Adversarial Simulation View):**
   - Natural language search with automatic constraint parsing (`/authorizations/parse-intent`).
   - Multi-agent swarm team selection (`agent_hardware`, `agent_travel`, `agent_supplies`) with quota tracking.
   - Streaming reasoning and product recommendations.
   - 1-Click **Adversarial Attack Simulator Pills** to test defenses against:
     - Prompt Injection Bypass
     - Hard Budget Ceiling Breach (₹48,000 cart vs ₹5,000 ceiling)
     - Stealth Shipping Surcharge (+₹850 drift)
     - Rogue Item SKU Swap
   - Live PayPal Sandbox Orders API v2 execution with idempotent request tokens.

2. **Policy Test Lab (Benchmark & Evaluation View):**
   - 1-click automated benchmark execution across all 7 transaction failure scenarios.
   - Side-by-side comparative architecture testing (Baseline A vs Baseline B vs Proposed PayPact).
   - Real-time quantitative metrics: 100% Defense Rate, 0 Unauthorized Spends, <0.1 ms latency.
   - Full comparative evaluation matrix.

3. **Audit Trail & Cryptographic Verifier (Audit & Dispute Defense View):**
   - Hash-chained immutable event timeline verifying chronological ledger integrity.
   - **Interactive Drag-and-Drop Receipt Verifier**: Inspect `.json` receipt files to check validity.
   - **1-Click Tamper Simulation**:
     - *Verify Authentic Receipt*: Evaluates HMAC-SHA256 signature against canonical digest (100% match).
     - *Simulate Tampered Amount (+₹1,000 Drift)*: Immediately flags cryptographic mismatch.
     - *Simulate Tampered Merchant*: Detects vendor phishing and payload manipulation.
   - In-card JSON inspector for dispute resolution review.
   - Direct link to interactive OpenAPI docs (`/docs`).

---

## 8. Tools & AI Used

| Tool | Role in PayPact |
|:---|:---|
| **PayPal Orders v2 API (Sandbox)** | Creates and captures real sandbox orders with `PayPal-Request-Id` idempotency, reconciles ambiguous timeouts via `GET /v2/checkout/orders/{id}`, and verifies webhook deliveries through `verify-webhook-signature`. |
| **PayPal JS SDK (`@paypal/react-paypal-js`)** | Buyer approval popup; the backend captures only after the pre-execution gate passes. |
| **Google Gemini (`gemini-2.5-flash`)** | Turns a natural-language purchase goal into structured constraints (budget, category, currency) and writes the recommendation rationale. Used when `GEMINI_API_KEY` is set. |
| **Ollama (`qwen2.5-coder:7b`)** | Local fallback for the same two jobs when Gemini is unavailable. |
| **Deterministic parser** | Final fallback, so the app and the test suite run with no AI service at all. |

The LLM only proposes. It never sees PayPal credentials and has no network path to PayPal; the deterministic policy engine decides what is executed.

---

## 9. Security Boundaries & Threat Model

- **No Agent Payment Authority:** The LLM agent produces structured JSON proposals only. It has zero network access to PayPal APIs and zero knowledge of client secrets.
- **Requests Are Verified, Not Guessed:** Before any proposal exists, a deterministic matcher (`backend/app/agent/requirements.py`) checks the item against what the request explicitly asks for: product type, route, travel class, one-way vs return, airline, quantity and nights. A request the catalogue cannot satisfy (a Mumbai flight, a business-class fare, a specific date, a train) is refused with the reason instead of being answered with the nearest item, and the LLM only explains a match that was already verified.
- **Fail-Closed Arithmetic:** Line-item subtotals, taxes, and shipping are re-summed by the server. Any mathematical discrepancy immediately rejects the proposal.
- **Tamper-Evident Ledger:** Every event is cryptographically linked:
  ```text
  event_hash = SHA-256(prev_event_hash + canonical_event_json)
  ```
- **Idempotency Tokens:** `PayPal-Request-Id` headers prevent duplicate financial capture.

---

## 10. Submission Details & Video Demo Script

- **Event:** PayPal AI Hackathon 2026 — *Build What's Next with PayPal and AI*
- **Public Repository:** [github.com/sahil-mangla/PayPact](https://github.com/sahil-mangla/PayPact)
- **Demo Walkthrough Video (< 3 minutes):**
  1. *0:00 - 0:30:* The Problem — Why autonomous AI purchasing agents fail when checkout details drift.
  2. *0:30 - 1:00:* Setting constraints in the Purchase Agent and completing a nominal PayPal sandbox checkout.
  3. *1:00 - 1:45:* Injecting +₹850 shipping drift and showing how the pre-execution gate intercepts unauthorized spend.
  4. *1:45 - 2:30:* Integrity Lab benchmark matrix showing the 100% vs 14.3% contrast across Baselines A, B, and PayPact.
  5. *2:30 - 3:00:* Tamper-evident audit trail and conclusion.

---

## 11. License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
