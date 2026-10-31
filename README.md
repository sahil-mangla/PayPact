# PayPact — Agent Payment Integrity Layer (APIL) with PayPal

> **PayPal AI Hackathon 2026 Submission**  
> *Build What's Next with PayPal and AI*  
> **Repository:** [github.com/sahil-mangla/PayPact](https://github.com/sahil-mangla/PayPact)  
> **Demo video (YouTube, under 3 min):** **TODO: add the public YouTube link before submitting**  
> **Hosted demo:** **TODO: add the deployed URL, or delete this line and rely on the run instructions in Section 4**  
> **License:** Apache 2.0  

**In one sentence:** PayPact is a deterministic gate between an LLM shopping agent and PayPal Orders v2. The model only proposes; money moves only if the exact proposal the user approved still passes policy at the moment of capture.

**Who it is for:** developers and companies putting an AI agent in front of a checkout, who need a way to prove that what was paid is what was approved.

**Built during the submission period** (opened 2026-10-01); the git history shows when:
- **Oct 19 to 21:** core build, including the policy engine, state machine, PayPal Orders v2 client, agent, audit ledger, receipts, Integrity Lab and the dashboard.
- **Oct 28:** webhook verification, receipt signing with a server-held secret, request matching, deployment config and the Apache 2.0 license.
- **Oct 31:** a security and correctness pass on the payment path (capture guards, settlement checks, webhook handling, budget reservation, input validation), plus tests and documentation.

**Built with AI assistance:** the code was written with AI coding assistants, including Claude Code. The shipped app also uses Gemini and Ollama at run time (Section 8).

**How this relates to existing agent-payment work:** protocols such as Google's AP2 define signed mandates that authorize an agent to buy. PayPact does not implement AP2 or any protocol. It demonstrates one idea end to end on PayPal Orders v2: bind what the user approved to a fingerprint, and re-check it, along with policy and amount, at the moment of payment.

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

Two kinds of caller reach the same coordinator: the web dashboard over REST, and any outside AI agent over MCP (see "Use PayPact from any AI agent (MCP)" below). Only the policy owner can approve: the dashboard holds an owner token returned when the policy is registered, and the owner can also mint a one-time approval link for a single proposal. An agent never receives either.

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
| **Baseline A (No Gate)** | 7 | 1 | **14.3%** | 6 | 0.1 ms |
| **Baseline B (Static Gate)** | 7 | 4 | **57.1%** | 3 | 0.1 ms |
| **PayPact (APIL)** | 7 | 7 | **100.0%** | **0** | **0.1 ms** |

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

The automated tests exercise the live code paths (order creation, capture, reconciliation, webhooks) against a fake PayPal served over `httpx.MockTransport`, so they run without credentials; the real sandbox is only exercised by following the steps above.

The sandbox does not support INR, so INR amounts are converted to USD at a fixed demo rate (83 INR per USD, override with `INR_TO_USD_RATE`) before the order is created.

### Configuration

| Variable | Default | Purpose |
|:---|:---|:---|
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | unset | Sandbox REST app credentials. With both set the backend uses live sandbox; otherwise mock mode. |
| `PAYPAL_MOCK_MODE` | unset | `true` forces offline mock mode even when credentials are set. |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` | The backend refuses any non-sandbox URL unless `ALLOW_LIVE_PAYPAL=true`. |
| `PAYPAL_WEBHOOK_ID` | unset | Required for `POST /api/webhooks/paypal`; without it every delivery is refused. |
| `APIL_SIGNING_SECRET` | random per process | HMAC key for audit receipts. Set it to keep receipts verifiable across restarts. |
| `GEMINI_API_KEY` | unset | Enables Gemini for intent parsing and for choosing the product through function calls. |
| `GEMINI_DAILY_CALL_LIMIT` | `500` | Daily cap on Gemini calls; past it the app falls back to local or deterministic parsing. `0` disables the cap. |
| `LLM_RATE_LIMIT_PER_MINUTE` | `30` | Per-client limit on the two endpoints that call an LLM. `0` disables it. |
| `ENABLE_WEBHOOK_SIMULATION` | unset | `/api/webhooks/simulate` always works in mock mode; against live PayPal it is off unless this is `true`. |
| `INR_TO_USD_RATE` | `83` | INR per USD for the sandbox conversion. |
| `CORS_ORIGINS` | localhost origins | Comma-separated allowed origins, or `*`. |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Base URL of the web app, used to build one-time approval links (`<base>/approve/<token>`). |
| `TOKEN_RATE_LIMIT_PER_MINUTE` | `60` | Per-client limit on the owner-token and approval-link endpoints. `0` disables it. |
| `NEXT_PUBLIC_API_URL` / `BACKEND_URL` | `http://localhost:8000` | Where the Next.js `/api` proxy sends requests. |

### What to type

The agent only buys what the nine-item catalogue actually contains, so a request outside it is refused with a reason. The quick-prompt and attack chips cover the interesting cases. Free-text examples that work: `Find a wireless mechanical keyboard under ₹5,000, auto-buy under ₹4,000` or `Book an economy flight from New Delhi to Bangalore under ₹5,000`. Prices are in rupees, so state your budget in rupees; a budget in another currency is refused rather than guessed.

### Test suites

```bash
# Backend: 271 tests (policy, state machine, webhooks, API, owner approval, MCP, agent, crypto, benchmark)
cd backend && source .venv/bin/activate && pytest -q

# Frontend: 93 tests, plus lint, typecheck and a production build
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
   - `GEMINI_API_KEY`: Enables Gemini for intent parsing and for choosing the product through function calls (see Section 8). Calls are capped per day (`GEMINI_DAILY_CALL_LIMIT`) and the LLM endpoints are rate limited per client, because the hosted demo has no user accounts.
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
     - *Tamper Price (+₹1,000 Drift)*: Immediately flags cryptographic mismatch.
     - *Tamper Merchant Identity*: Detects vendor phishing and payload manipulation.
   - In-card JSON inspector for dispute resolution review.
   - Direct link to interactive OpenAPI docs (`/docs`).

---

## Use PayPact from any AI agent (MCP)

PayPact is also a Model Context Protocol server, so an agent in Claude Desktop, or any MCP client, can request purchases under a policy you own. It talks to the same in-process coordinator as the web app, so what an agent proposes appears in the dashboard's **Agent requests** panel, labelled as coming from an outside agent.

**The four tools**

| Tool | What it does |
|:---|:---|
| `search_products(query)` | Searches the nine-item catalogue and returns a compact list (SKU, name, merchant, price). |
| `propose_purchase(policy_id, request, agent_id)` | Runs the shopper agent and the policy gate for a policy you give it. Returns the checkout id, the decision (`ALLOW`, `REQUIRE_APPROVAL` or `REJECT`), plain-language reasons, the total and a `next_step`. |
| `get_checkout(checkout_id)` | Returns a checkout's state, decision, amounts and any failure reason. |
| `pay(checkout_id)` | Pays an authorized checkout. The gate re-runs first. In mock mode it returns `PAID` or the reason it was blocked; against live PayPal it returns the PayPal URL the human buyer must open. |

**The guarantee.** There is no approve tool, no revoke tool and no policy-creation tool, and no tool result ever contains an owner token or an approval-link token. When a purchase needs approval, `pay` is refused until the owner approves it, either in the dashboard or through a one-time link (below). Prices always come from the catalogue, so a price written in the request text does not matter.

**How the owner approves.** Registering a policy returns an `owner_token` once; only its SHA-256 hash is stored. `POST /api/checkouts/{id}/approve` and `POST /api/authorizations/{id}/revoke` need it in an `X-Owner-Token` header: a missing token returns 401, a wrong one 403, and both are written to the audit ledger as "Approval refused". The dashboard keeps the token in the browser session and sends it for you. For approving from another device, **Copy approval link** mints a one-time URL (`<FRONTEND_BASE_URL>/approve/<token>`), bound to that checkout and its proposal fingerprint, valid for 30 minutes and for a single use. Opening it shows the merchant, items, total and reasons, and an Approve button.

**To try it:** register a policy in the dashboard, copy the policy id from the Agent requests panel, give it to the agent, and approve what arrives.

**Hosted (streamable HTTP).** The backend mounts the server at `/mcp`. In an MCP client that supports remote servers, add the URL. For Claude Desktop, which launches local servers, bridge it with `mcp-remote`:

```json
{
  "mcpServers": {
    "paypact": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<your-backend>/mcp"]
    }
  }
}
```

**Local (stdio).**

```json
{
  "mcpServers": {
    "paypact": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/paypact/backend"
    }
  }
}
```

The same command from a shell is `cd backend && python -m app.mcp_server`. A stdio server is its own process with its own in-memory state, so its policies and checkouts are not the web UI's. Use the hosted `/mcp` endpoint, or point both at one backend, when you want to approve in the dashboard. Without credentials the server runs in mock mode, like the rest of the app.

---

## 8. Tools & AI Used

| Tool | Role in PayPact |
|:---|:---|
| **PayPal Orders v2 API (Sandbox)** | Creates and captures real sandbox orders with `PayPal-Request-Id` idempotency, reconciles ambiguous timeouts via `GET /v2/checkout/orders/{id}`, and verifies webhook deliveries through `verify-webhook-signature`. |
| **PayPal JS SDK (`@paypal/react-paypal-js`)** | Buyer approval popup. The order is created server-side after the gate passes, and the capture endpoint re-runs the gate (revocation, expiry, fingerprint) and checks the captured amount before a checkout can become PAID. |
| **Google Gemini (`gemini-2.5-flash`)** | Turns a natural-language purchase goal into structured constraints (budget, category, currency), then chooses the product by calling `search_products`, `get_product` and `choose_product`. Used when `GEMINI_API_KEY` is set. |
| **Ollama (`qwen2.5-coder:7b`)** | Local fallback for intent parsing and the recommendation text when Gemini is unavailable. It does not choose products. |
| **Deterministic parser** | Final fallback, so the app and the test suite run with no AI service at all. |

The LLM only proposes. It never sees PayPal credentials and has no network path to PayPal; the deterministic policy engine decides what is executed. The AI's role is deliberately narrow:
- It turns the user's sentence into policy numbers, and a number is accepted only if the user actually typed it. A budget the model invents is ignored.
- It chooses the product through tool calls. The SKU must have been returned by a tool, must satisfy the request and the agent's category, and is priced from the catalogue. Otherwise the deterministic ranking decides, and the UI shows the tool calls and any override.
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
- **Approval needs the owner token or a one-time link, but there are no user accounts.** The owner token is a bearer secret held in the browser session, so anyone who gets it is the owner. Whoever registers a policy owns it: an agent with raw REST access could register a policy of its own and approve against that (the MCP surface has no policy tool, so an MCP agent cannot). Approval links are shown in the dashboard to be copied, not emailed or pushed anywhere. The `/mcp` endpoint has no authentication of its own, and the audit tab still lists the whole instance's events. Rate limits and a daily Gemini cap bound the cost. Real use would need authentication, per-user scoping and delivery of approval requests to the owner out of band.
- **The model chooses what to propose, not what is allowed.** With `GEMINI_API_KEY` set, Gemini picks the product through function calls (`search_products`, `get_product`, `choose_product`). Its pick is accepted only if it is a SKU a tool returned and it satisfies the request and the agent's category; it is priced from the catalogue, and the deterministic policy gate then approves or blocks it. Without a key, or if Gemini fails or is overruled, a deterministic ranking picks instead. Intent parsing is still a single Gemini call with a regex fallback. This loop is tested against a scripted fake Gemini; it has not yet been run against the live API.
- **A capture whose amount differs from the approval is flagged, not refunded.** The checkout is marked failed with a ledger entry and the capture id, and needs manual review in PayPal.
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
  2b. *Optional, about 20 s:* An outside agent connected over MCP proposes a purchase and its `pay` call is refused; the request appears in Agent requests, the owner opens the one-time approval link, approves, and `pay` then succeeds. A request to approve without the owner token is refused and shows in the Audit Trail.
  3. *1:00 - 1:50:* Click the Stealth Shipping Drift and Rogue SKU Swap chips; each ends in a block before PayPal is called. Then the Prompt Injection chip, which is refused with a reason.
  4. *1:50 - 2:20:* Audit Trail: hash-chained timeline, then drop in a receipt and use the tamper simulation to show the signature fail.
  5. *2:20 - 2:45:* Policy Test Lab (described honestly as scripted regression scenarios), then the repository and the deployed app.

---

## 11. License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
