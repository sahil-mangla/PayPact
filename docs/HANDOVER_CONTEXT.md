# Project Handover Context — AI-Agent Payment Integrity

> **Purpose:** This document is the source of truth for continuing the PayPal AI Hackathon project across chats, tools, or collaborators. It records the problem rationale, research context, product thesis, scope, architecture, milestones, evaluation plan, and open decisions.
>
> **Working title:** IntentLock (temporary; name collision risk identified)
>
> **Last updated:** 2026-10-18
>
> **Hackathon:** PayPal AI Hackathon 2026 — Build What's Next with PayPal and AI
>
> **Official deadline:** November 12, 2026, 12:00 PM Pacific Time (verify on Devpost before submission).

---

## 1. Executive Summary

We are exploring a focused product for AI-agent payments: an **AI purchasing application with a deterministic authorization layer and a reproducible transaction-integrity evaluation harness**.

The AI agent interprets a user's request and proposes a purchase. It does not authorize itself to spend money. A separate backend policy engine evaluates the proposed transaction against confirmed user constraints. A payment service executes only permitted actions through the PayPal sandbox, then verifies and records the transaction state.

The differentiator is **not** simply “AI with spending limits” or “a new secure-payments protocol.” Those concepts overlap with existing standards and research. The proposed contribution is a practical, testable evaluation of whether an application preserves the user's authorization when transaction details or application state change between proposal and execution.

The project should answer this question:

> **How reliably can a purchasing application preserve user authorization when transaction details or application state change between proposal and execution?**

The product will have two experiences:

1. **Purchase Agent** — the user describes a purchase, reviews a recommendation, and completes an eligible PayPal sandbox checkout.
2. **Integrity Lab** — the user or judge runs controlled scenarios (e.g., price drift, product substitution, revoked authorization, duplicate submission, prompt injection) and sees the policy decision, enforcement point, transaction state, and audit record.

The goal is a credible, polished hackathon MVP with a clear end-to-end demo—not an enterprise payment-security platform or a new payment protocol.

---

## 2. Hackathon Requirements and Constraints

Treat the official event pages as authoritative; re-check them before submission.

- Event: <https://paypalaihackathon.devpost.com/>
- Rules: <https://paypalaihackathon.devpost.com/rules>
- Resources: <https://paypalaihackathon.devpost.com/resources>
- Dates: <https://paypalaihackathon.devpost.com/details/dates>
- FAQs: <https://paypalaihackathon.devpost.com/details/faqs>
- Updates: <https://paypalaihackathon.devpost.com/updates>

Requirements identified in prior research:
- Meaningful integration of PayPal technology and AI.
- A functional application, not just a static mockup.
- Public source-code repository with an open-source license.
- README with setup/run instructions.
- Publicly accessible YouTube demo under three minutes.
- Complete Devpost submission, including repository and demo links.
- No real credentials committed to source control.
- Check current official rules for eligibility, team, licensing, submission and sponsor-prize details.

Deadline planning:
- Current planning date: October 18, 2026.
- Aim to submit by November 11, 2026, leaving November 12 as a buffer.
- The earlier timeline is only a planning aid. Development is organized below by **milestones and exit criteria**, not calendar phases. Reprioritize according to actual progress.

---

## 3. Problem Statement

AI agents can interpret natural-language goals and call tools, but payment execution needs precise, deterministic authorization. Between the user's initial instruction and final payment request, important details can change:

- Price, tax, shipping, currency, merchant, product, or quantity.
- User authorization or spending policy.
- The application state or checkout attempt.
- Whether a previous attempt already created a financial effect.
- The trustworthiness or freshness of external content used by the agent.

A valid model output or technically valid payment request is not proof that the resulting transaction still matches the user's confirmed intent.

The application should therefore distinguish:
1. **Intent:** What the user requested.
2. **Authorization:** What actions are permitted under confirmed rules.
3. **Proposal:** What the AI recommends.
4. **Execution:** What the backend actually sends to PayPal.
5. **Outcome:** What PayPal reports happened.
6. **Evidence:** What the application records about each decision and state transition.

Do not claim to solve all agentic-payment security. Pick a bounded threat model, test it, and state limitations honestly.

---

## 4. Product Thesis and User Story

### Core pitch

**An AI purchasing agent with a transaction-integrity evaluation system that tests whether payment requests remain consistent with the user's authorization throughout the transaction lifecycle.**

### Example user request

> Find a mechanical keyboard suitable for programming. My maximum total budget is ₹5,000. You may purchase automatically only if the final price is below ₹4,000. Otherwise, ask me for approval.

Illustrative structured constraints (final schema to be designed and validated):

```json
{
  "product_category": "mechanical keyboard",
  "maximum_total": 5000,
  "automatic_purchase_limit": 4000,
  "currency": "INR",
  "require_approval_above_limit": true
}
```

The app should validate extracted constraints and have the user confirm them before they become an authorization record. The AI must not be able to edit the confirmed policy by generating new text.

### Purchase Agent flow

1. User enters a purchase request and constraints.
2. AI extracts a structured proposal; schema validation catches malformed or ambiguous outputs.
3. Product information is retrieved from a controlled catalogue initially.
4. Agent proposes a product and explains the recommendation.
5. Backend builds a canonical purchase proposal.
6. Deterministic policy engine evaluates the proposal against the current authorization and current transaction data.
7. If allowed, the backend creates/continues the PayPal sandbox checkout.
8. If approval is required, execution pauses until the user approves the exact proposal.
9. Payment outcome is verified using the appropriate PayPal API response and/or verified webhook flow.
10. A durable audit record captures the authorization decision and transaction state.

### Integrity Lab flow

The user chooses a scenario, sees its setup, runs it against the baseline/configuration under test, and receives:
- Expected result.
- Actual result.
- Whether the request was allowed, blocked, or routed to approval.
- Which policy check fired.
- Whether a PayPal action was attempted.
- Final transaction state.
- Audit evidence and a test result.

The lab must distinguish “request blocked before payment call” from “payment provider rejected the call” and from “a duplicate request was detected after an earlier payment had already succeeded.”

---

## 5. Differentiation: What This Project Is and Is Not

### It IS
- A practical AI-purchasing app.
- A deterministic authorization and transaction-state verification layer.
- A repeatable test harness for transaction-integrity failure scenarios.
- A measurable comparison between simpler controls and stronger lifecycle checks.
- A PayPal sandbox integration with clear audit evidence.

### It is NOT
- A claim to invent secure agentic payments.
- A replacement for PayPal security, AP2, or another payment protocol.
- A general fraud detector trained on synthetic data.
- A guarantee that all prompt injection or payment fraud is prevented.
- A new payment protocol.
- A multi-agent system merely for complexity.
- A real-money payment product.

### Critical differentiation rule

Basic spending limits, approval buttons, signed mandates, stale authorization checks, provenance-aware authorization, and duplicate handling all have prior art. Do not present these individual features as novel. The defensible hackathon contribution is the **specific, reproducible application-level evaluation**, with a clearly defined threat model, controlled scenarios, measurable outcomes, and an end-to-end PayPal sandbox demonstration.

Before finalizing the name or claims, inspect the existing public IntentLock repositories listed in Section 7. Rename the project if necessary; a new name is preferable to confusion with prior projects.

---

## 6. Research and Existing Work to Account For

The following references informed the current direction. Verify their content and publication status directly before making detailed claims in the final Devpost page or README.

### Research papers and analysis

1. **IMF — “How Agentic AI Will Reshape Payments” (April 2026)**  
   https://www.elibrary.imf.org/view/journals/068/2026/004/article-A001-en.xml  
   Context: intent, authorization, settlement, accountability and the gap between probabilistic agent behavior and deterministic payment execution.

2. **“A Formal Analysis of Agent Payment Protocols” (2026 preprint)**  
   https://arxiv.org/abs/2609.00060  
   Context: formal analysis of x402, MPP, ACP and AP2; cross-stage consistency and protocol properties. Treat the authors' reported results as claims from a preprint, not independently established facts.

3. **“Beyond the Mandate: A Systematic Security Analysis of the Agent Payments Protocol” (2026 preprint)**  
   https://arxiv.org/abs/2608.23858  
   Context: AP2 security boundaries, agent interactions, external inputs and authorization artifacts. Verify details and publication status.

4. **CAPE — “Provenance-aware Semantic Authorization for Agentic Payments” (SSRN preprint, October 2026)**  
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7578318  
   Context: especially close overlap with provenance-aware authorization and transaction evidence. Do not claim novelty in this broad area without reviewing the full paper and its experiments.

5. **InjecAgent — “Benchmarking Indirect Prompt Injections in Tool-Integrated LLM Agents” (Findings of ACL 2024)**  
   https://aclanthology.org/2024.findings-acl.624/  
   Context: indirect prompt injection against tool-using agents. Any benchmark figures must be attributed to the paper's particular experimental setup.

### Protocol and implementation references

6. **Google AP2 specification**  
   https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/specification.md

7. **AP2 agent authorization**  
   https://ap2-protocol.org/ap2/agent_authorization/

8. **CrawlerPal, a prior PayPal Dev Days winner**  
   https://github.com/positiveblue/CrawlerPal  
   Context: paid access to digital content using an AI-agent-oriented payment flow; relevant precedent, so avoid cloning it.

9. **Existing projects using the name IntentLock**  
   - https://github.com/dsaitejreddy/intentlock-ai-payment-safety
   - https://github.com/CoderCartikey/intentlock  
   Inspect their current code, dates, licenses, tests, and scope before choosing a final name or claiming differentiation. Do not assume repository descriptions establish completeness or security.

10. **PayPal AI Hackathon rules and resources**  
    - https://paypalaihackathon.devpost.com/rules
    - https://paypalaihackathon.devpost.com/resources

### Research discipline

- Distinguish peer-reviewed papers, preprints, vendor specifications, and GitHub prototypes.
- Do not claim a feature is novel just because it is not in a quick search.
- Do not reproduce benchmark numbers without checking the original paper.
- Do not claim that a scenario is an actual vulnerability in PayPal or AP2 unless demonstrated by evidence.
- Do not send real payments or probe production systems. Use controlled fixtures and the PayPal sandbox.

---

## 7. Project Name

**IntentLock is temporary.** Public repositories already use this name for closely related concepts.

Do not spend milestone time on branding. Choose a distinct name before the public launch/Devpost submission. Until then, refer to the project internally as “Agent Payment Integrity Lab” or “APIL” if a neutral identifier is needed.

Potential naming criteria:
- Distinct from existing GitHub projects and payment protocols.
- Does not imply formal verification or security guarantees the product does not provide.
- Short enough for a demo and repository.
- Check GitHub, web search, and relevant trademarks before committing.

---

## 8. Proposed Architecture

Keep the architecture simple and make trust boundaries explicit.

```text
                          USER
                            |
                            v
                      Next.js UI
                            |
                            v
                        Backend API
                            |
                +-----------+-----------+
                |                       |
                v                       v
             AI Agent              Current Policy
                |                  + Authorization
                v                       |
         Product / Tool Data             |
                |                       |
                v                       v
         Purchase Proposal ----> Verification Gate
                                        |
                          +-------------+-------------+
                          |             |             |
                          v             v             v
                        ALLOW       APPROVAL        REJECT
                          |             |
                          |       User approves
                          +-------------+
                                        |
                                        v
                                Payment Service
                                        |
                                        v
                                 PayPal Sandbox
                                        |
                                        v
                             Verified Transaction State
                                        |
                                        v
                                  Audit Record
                                        |
                                        v
                                Integrity Lab / UI
```

### Suggested stack

- Frontend: Next.js + TypeScript.
- Backend: FastAPI.
- AI: LLM with structured outputs/tool calling; choose provider after feasibility test.
- Policy engine: Python, deterministic and independently testable.
- Database: SQLite for initial MVP; PostgreSQL only if it is justified by deployment/concurrency needs.
- Payments: PayPal sandbox.
- Tests: pytest; add API/integration tests.
- Product data: controlled local catalogue first; consider Channel3 only after core flow works.
- Deployment: Render or another reliable host, selected after a minimal deployment test.

### Architectural requirements

- The AI never edits or overrides the confirmed authorization policy.
- The backend—not the frontend—enforces policy.
- The exact transaction parameters are validated immediately before the payment action.
- The server calculates/validates total amounts; never trust client-provided totals.
- Payment state comes from PayPal's response and appropriately verified events, not from model text or a redirect alone.
- Webhooks must be verified according to PayPal documentation before they update authoritative state.
- Use idempotency/duplicate protection where supported and persist attempt state. Do not assume application-level deduplication guarantees settlement-level exactly-once behavior.
- A timeout is an ambiguous state until reconciled; do not blindly retry a potentially successful payment.
- Keep sandbox credentials in environment variables; never commit them.
- Avoid logging secrets or unnecessary personal data.

### Candidate application endpoints (not PayPal endpoints)

```text
POST /api/purchase-requests
POST /api/purchase-proposals
POST /api/authorizations
POST /api/checkouts
GET  /api/checkouts/{id}
POST /api/webhooks/paypal
POST /api/integrity-tests
GET  /api/integrity-tests/{run_id}
```

Do not implement every endpoint up front. Derive the API from domain flows and tests.

---

## 9. Domain Concepts to Model

Keep domain models explicit and validate them.

Potential concepts:
- `PurchaseRequest`: the user's natural-language goal.
- `AuthorizationPolicy`: confirmed constraints and permission scope.
- `AuthorizationVersion`: version/revision of a policy; changes invalidate incompatible pending actions.
- `ProductEvidence`: product/merchant/price data, source and observation timestamp.
- `PurchaseProposal`: canonical product and full price details proposed by the agent.
- `IntegrityCheck`: a named deterministic check with result and reason.
- `AuthorizationDecision`: allow, approval-required, or reject, with policy version and proposal fingerprint.
- `ApprovalRecord`: explicit user approval for a specific proposal/version.
- `CheckoutAttempt`: stable application identifier, idempotency data where supported, and lifecycle status.
- `PaymentObservation`: verified information from PayPal response/webhook/reconciliation.
- `AuditEvent`: append-oriented record of material state transitions.
- `ScenarioDefinition`: controlled test setup, perturbation, expected result and classification.
- `ScenarioRun`: inputs, configuration, outcome, latency, and evidence.

These are candidate concepts, not a demand to implement all of them immediately. Prefer the smallest model set that makes the first end-to-end flow correct.

### Canonical transaction fingerprint

Consider a canonical representation/hash for the exact proposal being authorized, including relevant fields such as:
- user/policy version;
- merchant identity;
- product identifier and selected variant;
- quantity;
- currency;
- item amount;
- shipping, tax, fees and final total;
- relevant expiry or validity window.

The exact fields depend on the supported checkout flow. Define canonicalization carefully and test it. A hash is only an integrity aid; it does not prove that source data is true or trustworthy.

---

## 10. Milestone-Based Development Plan

**Development is organized by milestones and exit criteria, not calendar phases.** Do not move to a milestone merely because a date passed. If a milestone fails, debug or reduce scope before proceeding.

### Milestone 0 — Research and Scope Freeze
### Milestone 1 — PayPal Sandbox Feasibility
### Milestone 2 — Deterministic Authorization Engine
### Milestone 3 — Purchase Proposal and Agent Integration
### Milestone 4 — Transaction Lifecycle Enforcement
### Milestone 5 — Reproducible Evaluation Harness
### Milestone 6 — Product UI and Integrity Lab
### Milestone 7 — Reliability, Security and Deployment
### Milestone 8 — Hackathon Submission and Demo

---

## 11. Initial Scenario Specifications
### Scenario A — Valid purchase
### Scenario B — Price drift
### Scenario C — Revoked authorization
### Scenario D — Product substitution
### Scenario E — Duplicate submission
### Scenario F — Indirect prompt injection fixture
### Scenario G — Ambiguous payment timeout

---

## 12. State and Audit Design Principles
- Lifecycle states
- Append-oriented audit records
- Fail closed boundaries

---

## 13. Open Decisions (Resolve Only When Needed)
1. Final name
2. LLM/provider
3. Payment flow
4. Currency
5. Product source
6. Persistence
7. Webhooks
8. Baseline design
9. Scope of duplicate
10. Research claims
11. Sponsor strategy

---

## 14. Out of Scope for the Initial MVP
- Multiple collaborating agents
- Real-money transactions
- New payment protocol
- Enterprise-wide policy management
- General-purpose fraud detection
- Cryptocurrency/blockchain

---

## 15. Definition of Done
Detailed verification checklist for hackathon readiness.
