# PayPact — Agent Payment Integrity Layer (APIL) with PayPal

> **PayPal AI Hackathon 2026 Submission**  
> *Build What's Next with PayPal and AI*  
> **Repository:** [github.com/sahil-mangla/PayPact](https://github.com/sahil-mangla/PayPact)  
> **Demo video (YouTube, under 3 min):** **TODO: add the public YouTube link before submitting**  
> **Hosted demo:** **TODO: add the deployed URL, or delete this line and rely on the run instructions in Section 4**  
> **License:** Apache 2.0  

**In one sentence:** PayPact is a deterministic gate between an LLM shopping agent and PayPal Orders v2. The model only proposes; money moves only if the exact proposal the user approved still passes policy at the moment of capture.

**Who it is for:** developers and companies putting an AI agent in front of a checkout, who need a way to prove that what was paid is what was approved.

**Built during the submission period:** the first commit is dated 2026-10-19 and all of the work in this repository was done after the submission period opened on 2026-10-01.

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

1. **Versioned User Policy:** Human-confirmed spending policies carry a version number, and a proposal prepared under an older version is rejected. The AI cannot change a policy; the server owns its spend and revocation state.
2. **Hierarchical Swarm Quota Trees:** Multi-agent teams (`agent_hardware`, `agent_travel`, `agent_supplies`) receive isolated sub-quotas with each purchase counted against both the agent's quota and the master budget. Checkouts that are mid-payment hold their amount, so parallel checkouts cannot overspend.
3. **Canonical Proposal Fingerprinting:** Every proposal is canonicalized and hashed using SHA-256 (binding exact SKU, merchant, line-items, taxes, and currency).
4. **Deterministic Pre-Execution Invariant Gate:** The gate runs before the PayPal order is created and again immediately before capture. It validates live state against the policy version, budget ceiling, revocation and the approved fingerprint, and a capture whose amount differs from the approval is never recorded as paid.
5. **HMAC-SHA256 Audit Receipts:** Every transaction, whether paid or blocked, exports a signed, tamper-evident receipt (`POST /api/receipt/verify`). HMAC is symmetric, so only the server that holds the signing secret can verify a receipt; this is tamper evidence, not third-party non-repudiation.
6. **Async Webhook Reconciliation:** Handles `PAYMENT.CAPTURE.REFUNDED` and `CUSTOMER.DISPUTE.CREATED` events with quota restoration. Each event is applied once, refunds are capped at the amount paid, and only a paid checkout can be refunded or disputed.
7. **Idempotency & State Machine:** Per-checkout locks and a guarded state machine, plus `PayPal-Request-Id` on order creation and capture, guard against duplicate billing. Re-running reconcile or capture on a paid checkout changes nothing.
8. **Integrity Lab:** A scripted suite that replays 7 failure modes against two simplified reference designs and PayPact (see Section 3 for what that does and does not show).

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

## 3. Integrity Lab: Scripted Failure-Mode Scenarios

The Integrity Lab replays 7 failure modes against three configurations. It is a **deterministic regression suite with illustrative baselines**, not an experiment on real agents or merchants:
- **Baseline A (Unconstrained):** a simplified design that builds a PayPal order straight from the agent's proposal, with no policy gates.
- **Baseline B (Static Gate):** a simplified design that checks policy once, when the proposal is generated, with no pre-execution validation.
- **PayPact (APIL):** the real coordinator in this repository: lifecycle state machine, canonical SHA-256 fingerprinting, pre-execution invariant gate and idempotency locks.

Baselines A and B are small hand-written stand-ins in [`backend/app/lab/benchmark.py`](backend/app/lab/benchmark.py), and the seven scenarios are the failure modes PayPact was designed for, so the 100% result shows the gate does what it was built to do, not that it beats other systems. All runs use the offline mock PayPal client, so the latency column measures the gate's own overhead and excludes any network time.

### Quantitative Summary Table
*(7 scenarios x 3 systems = 21 runs. Reproduce with `python3 scripts/run_eval.py`, which rewrites [`docs/BENCHMARK_RESULTS.json`](docs/BENCHMARK_RESULTS.json).)*

| System Configuration | Scenarios | Passed Scenarios | Pass Rate (%) | Unauthorized Spends | Avg Latency (mock) |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Baseline A (No Gate)** | 7 | 1 | **14.3%** | 6 | 0.10 ms |
| **Baseline B (Static Gate)** | 7 | 4 | **57.1%** | 3 | 0.09 ms |
| **PayPact (APIL)** | 7 | 7 | **100.0%** | **0** | **0.09 ms** |

*Note on calculations: 1 / 7 = 14.3%, 4 / 7 = 57.1%, 7 / 7 = 100.0%.*

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
- A free PayPal developer account for live sandbox mode (optional; with no credentials the backend runs fully offline in mock mode)

### Fastest path for judges: offline mock mode (no accounts, about 2 minutes)

```bash
git clone https://github.com/sahil-mangla/PayPact.git
cd PayPact

# Terminal 1: backend on http://localhost:8000
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python3 -m uvicorn app.main:app --port 8000

# Terminal 2: frontend on http://localhost:3000
cd frontend
npm ci --legacy-peer-deps
npm run dev
```

Open **http://localhost:3000**. `GET http://localhost:8000/api/health` should report `"paypal_mode": "mock"`. In mock mode the whole flow works, with PayPal orders simulated in memory, so there is no PayPal popup. Try the four **Adversarial Attack Simulator** chips: each runs end to end on one click and ends in a visible block, and a normal purchase ends in a signed receipt you can verify on the **Audit Trail** tab.

### Live PayPal sandbox mode (real Orders v2 calls and the PayPal popup)

1. Sign in at [developer.paypal.com](https://developer.paypal.com/) and open **Apps & Credentials** with the **Sandbox** toggle selected.
2. Click **Create App** (type: Merchant). Copy the app's **Client ID** and **Secret**.
3. Open **Testing Tools > Sandbox Accounts** and use (or create) a **Personal** (buyer) account. You will log in with its email and password in the PayPal popup. Do not use your real PayPal login.
4. Put the credentials in the backend environment, either in `backend/.env` or exported in the shell:
   ```bash
   PAYPAL_CLIENT_ID=<sandbox client id>
   PAYPAL_CLIENT_SECRET=<sandbox secret>
   ```
5. Put the same client ID in `frontend/.env.local` so the PayPal buttons render:
   ```bash
   NEXT_PUBLIC_PAYPAL_CLIENT_ID=<sandbox client id>
   ```
6. Restart both servers. `GET /api/health` now reports `"paypal_mode": "live_sandbox"`.
7. Run a purchase, press **Pay with PayPal**, and approve it with the sandbox buyer account. The backend re-checks the policy and the amount when it captures.

The sandbox does not support INR, so INR amounts are converted to USD at a fixed demo rate (83 INR per USD, override with `INR_TO_USD_RATE`) before the order is created.

### Configuration

| Variable | Default | Purpose |
|:---|:---|:---|
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | unset | Sandbox REST app credentials. With both set the backend uses live sandbox; otherwise mock mode. |
| `PAYPAL_MOCK_MODE` | unset | `true` forces offline mock mode even when credentials are set. |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` | The backend refuses any non-sandbox URL unless `ALLOW_LIVE_PAYPAL=true`. |
| `PAYPAL_WEBHOOK_ID` | unset | Required for `POST /api/webhooks/paypal`; without it every delivery is refused. |
| `APIL_SIGNING_SECRET` | random per process | HMAC key for audit receipts. Set it to keep receipts verifiable across restarts. |
| `GEMINI_API_KEY` | unset | Enables Gemini for intent parsing and the recommendation rationale. |
| `GEMINI_DAILY_CALL_LIMIT` | `500` | Daily cap on Gemini calls; past it the app falls back to local or deterministic parsing. `0` disables the cap. |
| `LLM_RATE_LIMIT_PER_MINUTE` | `20` | Per-client limit on the two endpoints that call an LLM. `0` disables it. |
| `ENABLE_WEBHOOK_SIMULATION` | unset | `/api/webhooks/simulate` always works in mock mode; against live PayPal it is off unless this is `true`. |
| `INR_TO_USD_RATE` | `83` | INR per USD for the sandbox conversion. |
| `CORS_ORIGINS` | localhost origins | Comma-separated allowed origins, or `*`. |
| `NEXT_PUBLIC_API_URL` / `BACKEND_URL` | `http://localhost:8000` | Where the Next.js `/api` proxy sends requests. |

### Test suites

```bash
# Backend: 189 tests (policy, state machine, webhooks, API, agent, crypto, benchmark)
cd backend && source .venv/bin/activate && pytest -q

# Frontend: 32 tests, plus lint, typecheck and a production build
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```

### Run the benchmark from the command line
```bash
./backend/.venv/bin/python3 scripts/run_eval.py   # rewrites docs/BENCHMARK_RESULTS.json
```

---

## 5. Automated CI/CD Pipeline (GitHub Actions)

The repository includes a GitHub Actions workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) that executes on every push and pull request:

- **Backend Matrix Job (`backend-tests`):** Runs the full backend suite on Python 3.11 and 3.12.
- **Frontend Job (`frontend-tests`):** `npm ci`, lint, typecheck, Vitest, then a Next.js production build.
- **Continuous Deployment Job (`deploy-render`):** Triggers Render deploy hooks on a push to `main`, only when the hook secrets are configured.

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
   - `GEMINI_API_KEY`: Enables Gemini for intent parsing and recommendation rationale (see Section 8). Calls are capped per day (`GEMINI_DAILY_CALL_LIMIT`) and the LLM endpoints are rate limited per client, because the hosted demo has no user accounts.
   - `ENABLE_WEBHOOK_SIMULATION`: leave unset on a public deployment. The simulated-webhook endpoint fabricates PayPal events, so against live PayPal it stays off unless this is `true`.
   - Free-tier services sleep when idle; the first request after a pause can take about a minute, and the UI says so.
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
     - Hard Budget Ceiling Breach (₹4,699 keyboard vs ₹3,000 ceiling)
     - Stealth Shipping Surcharge (+₹850 drift)
     - Rogue Item SKU Swap
   - Live PayPal Sandbox Orders API v2 execution with idempotent request tokens.

2. **Policy Test Lab (Benchmark & Evaluation View):**
   - 1-click automated benchmark execution across all 7 transaction failure scenarios.
   - Side-by-side comparative architecture testing (Baseline A vs Baseline B vs Proposed PayPact).
   - Per-system metrics: defense rate, unauthorized spends and gate latency (against the offline mock PayPal client).
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
| **PayPal JS SDK (`@paypal/react-paypal-js`)** | Buyer approval popup. The order is created server-side after the gate passes, and the capture endpoint re-runs the gate (revocation, expiry, fingerprint) and checks the captured amount before a checkout can become PAID. |
| **Google Gemini (`gemini-2.5-flash`)** | Turns a natural-language purchase goal into structured constraints (budget, category, currency) and writes the recommendation rationale. Used when `GEMINI_API_KEY` is set. |
| **Ollama (`qwen2.5-coder:7b`)** | Local fallback for the same two jobs when Gemini is unavailable. |
| **Deterministic parser** | Final fallback, so the app and the test suite run with no AI service at all. |

The LLM only proposes. It never sees PayPal credentials and has no network path to PayPal; the deterministic policy engine decides what is executed. The AI's role is deliberately narrow:
- It turns the user's sentence into policy numbers, and a number is accepted only if the user actually typed it. A budget the model invents is ignored.
- It writes the recommendation text. That text is dropped if it cites a price or SKU that is not in the verified proposal.
- It does not choose the product. Matching against the catalogue is deterministic and ignores merchant-written descriptions.

---

## 9. Security Boundaries & Threat Model

- **No Agent Payment Authority:** The LLM agent produces structured JSON proposals only. It has zero network access to PayPal APIs and zero knowledge of client secrets.
- **Requests Are Verified, Not Guessed:** Before any proposal exists, a deterministic matcher (`backend/app/agent/requirements.py`) checks the item against what the request explicitly asks for: product type, route, travel class, one-way vs return, airline, quantity and nights. A request the catalogue cannot satisfy (a Mumbai flight, a business-class fare, a specific date, a train) is refused with the reason instead of being answered with the nearest item, and the LLM only explains a match that was already verified.
- **Fail-Closed Arithmetic:** Line-item subtotals, taxes, and shipping are re-summed by the server. Any mathematical discrepancy immediately rejects the proposal.
- **Tamper-Evident Ledger:** Every event is cryptographically linked:
  ```text
  event_hash = SHA-256(prev_event_hash + canonical_event_json)
  ```
- **Idempotency Tokens:** `PayPal-Request-Id` headers on order creation and capture, with per-checkout locks, guard against duplicate financial capture.
- **Charge Comes From Stored Data:** The PayPal order is built from the proposal the server stored, never from fields sent with the execute request.
- **Sandbox Only By Default:** The client refuses a non-sandbox `PAYPAL_BASE_URL` unless `ALLOW_LIVE_PAYPAL=true`.

### Known limitations (demo scope)

- **State is in memory.** Policies, checkouts and the audit ledger reset on a restart or a free-tier sleep. The ledger is hash-chained, but nothing anchors its head outside the process.
- **Drift is simulated.** There is no real merchant feed. The attack chips inject price drift and SKU substitution at execute time to show the gate catching it.
- **No user accounts.** Anyone who can reach a deployment can use it, and the audit tab lists the whole instance's events. Rate limits and a daily Gemini cap bound the cost; real use would need authentication and per-user scoping.
- **Receipts use HMAC.** They are tamper-evident to the server that holds the key, not independently verifiable. Receipts do not carry a key ID, so rotating `APIL_SIGNING_SECRET` invalidates old ones.
- **Small fixed catalogue.** Nine fixture products (including one adversarial listing) stand in for merchants.
- **Money uses floats rounded to cents,** and INR is converted to USD at a fixed demo rate for the sandbox.
- **Next.js 14 has open `npm audit` advisories** (image optimization, server actions, rewrite handling). The app uses none of those features, and fixing them needs a major framework upgrade, so they are noted here instead of silenced.

---

## 10. Submission Details & Video Demo Script

- **Event:** PayPal AI Hackathon 2026 — *Build What's Next with PayPal and AI*
- **Public Repository:** [github.com/sahil-mangla/PayPact](https://github.com/sahil-mangla/PayPact)
- **Demo Walkthrough Video (target 2:45, hard limit 3:00):**
  1. *0:00 - 0:20:* The problem: an agent can pay for something different from what the user approved.
  2. *0:20 - 1:00:* Type a goal, show the parsed policy and a verified proposal, approve it, and pay in the PayPal sandbox popup (live mode) to a signed receipt.
  3. *1:00 - 1:50:* Click the Stealth Shipping Drift and Rogue SKU Swap chips; each ends in a block before PayPal is called. Then the Prompt Injection chip, which is refused with a reason.
  4. *1:50 - 2:20:* Audit Trail: hash-chained timeline, then drop in a receipt and use the tamper simulation to show the signature fail.
  5. *2:20 - 2:45:* Policy Test Lab (described honestly as scripted regression scenarios), then the repository and the deployed app.

---

## 11. License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
