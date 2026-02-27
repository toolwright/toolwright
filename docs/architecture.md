# Toolwright Architecture

Compiler + Lockfile + Verification Contracts + Drift Gates
Governance for agents, enforced by deterministic build artifacts
February 2026

> Status: **[SHIPPED]** = working in current release | **[ALPHA]** = code exists, limited | **[PLANNED]** = design only
> Canonical feature status lives in the README Feature Status table.
> Contributor rule: If code and docs disagree, README Feature Status wins, then code, then this file.

## v1 Execution Lock (2026-02-10)

The v1 release baseline is locked to:

`mint -> diff -> gate -> run -> drift -> verify`

Canonical command surface:

- Core: `init`, `mint`, `diff`, `gate`, `serve`, `run`, `drift`, `verify`, `demo`
- More: `capture`, `workflow`, `auth`
- Advanced (behind `--help-all`): `compile`, `bundle`, `lint`, `doctor`, `config`, `inspect`, `enforce`, `migrate`
- No aliases -- one best name per command

Hard v1 contracts in force:

- fail-closed runtime lockfile enforcement
- Ed25519 approval signatures + signer identity
- root state lock for mutating commands
- runtime egress safety (scheme, DNS/IP, redirect-hop checks)
- app/idp host split (`allowed_hosts.app`, `allowed_hosts.idp`)
- versioned `contracts.yaml` and authoritative scope ownership
- provenance verification mode with ranked candidate evidence
- DecisionTrace audit JSONL schema for runtime decisions
- export boundary excluding auth state, signing keys, raw secrets

See implementation-level specs:

- `docs/playbook-spec.md`
- `docs/verification-spec.md`
- `docs/evidence-redaction-spec.md`
- `docs/ci-gate-policy.md`
- `docs/compatibility-matrix.md`
- `docs/known-limitations.md`
- `docs/threat-model-boundaries.md`

## 0. Why this rewrite

The previous spec centered “Full Meta” and agent-driven discovery. 
That creates the wrong v1 product shape:

* It pushes you toward “agents governing themselves,” which is a security and sales killer.
* It competes head-on with runtime gateway and governance vendors.
* It delays the real wedge: deterministic tool supply chain plus outcome verification plus drift gates in CI.

This update reframes Toolwright as a **build system** that produces **standard artifacts** (toolpack, lockfile, verification contract, evidence) that runtime layers can enforce. The control plane exists, but it is **human and CI first**, and **never** a channel for agents to request more power.

---

## 1. Executive goals [SHIPPED]

### 1.1 vNext outcomes

By the end of vNext, Toolwright must support:

1. **Deterministic supply chain**

* `toolwright mint` compiles raw captures (HAR, Playwright traces, optional OpenAPI) into a runnable toolpack with stable IDs and canonical schemas.

2. **Lockfile governance loop**

* `toolwright diff` shows exactly what changed and classifies risk.
* `toolwright gate allow` writes an immutable governance decision into `toolwright.lock`.
* Any capability expansion requires explicit approval.

3. **Verification contracts**

* `toolwright verify` runs assertion-based verification against multi-signal post-conditions (API state, UI semantics, optional event signals).
* Verification produces a structured report and evidence bundle that humans can audit and CI can gate on.

4. **Drift gates tied to verification**

* `toolwright drift` detects changes in tool surface and verification contract behavior.
* Drift fails CI by default for high-risk changes or contract breaks.

5. **Runtime parity for enforcement decisions**

* The same policy evaluation and scope enforcement is used by both:

  * MCP serve mode
  * optional HTTP gateway/proxy mode

6. **Safe defaults**

* Default deny, strict egress allowlists, deterministic redaction, no silent expansion.
* No secrets in agent-visible surfaces.

### 1.2 Non-goals (locked)

1. **No agent-driven scope expansion**

* No tool that allows an agent to request more privileges.
* No “negotiation” interface where agents ask for expanded access.

2. **No agent-led approvals**

* Approvals are always human or CI-bound with explicit signers.
* No in-protocol “approve” tools exposed to agents.

3. **Not a runtime gateway product**

* Toolwright feeds gateways. It does not compete as the primary runtime layer.

4. **No “mathematical proof of correctness”**

* Toolwright provides deterministic evidence that post-conditions hold, not proofs.

---

## 2. Terms and invariants [SHIPPED]

### 2.1 Terms

* **Capture**: recorded traffic and related artifacts from HAR, Playwright, and optionally OpenAPI fixtures. 
* **Endpoint**: normalized API interaction with stable identity, inferred schema, and risk classification.
* **Tool**: agent-callable function compiled from endpoints.
* **Toolpack**: bundle of tools, schemas, policies, verification contracts, and evidence pointers.
* **Lockfile**: a signed governance artifact that binds capabilities, scopes, risk, and verification contract versions to approvals.
* **Verification contract**: assertion specs defining post-conditions for workflows and tools.
* **Evidence bundle**: redacted, digest-addressed artifacts produced by mint, verify, and runtime decisions.

### 2.2 Invariants (must always hold)

(These remain core, but clarified and tightened from the prior draft.) 

1. **No silent privilege escalation**

* New hosts, new tools, new write surfaces, weaker constraints, or broader scopes require explicit approval.

2. **Deterministic compilation**

* Same inputs + config must produce identical artifacts and digests.

3. **Default deny**

* Runtime evaluation starts at deny and requires explicit allow paths.

4. **Secrets never enter the agent-visible surface**

* No raw tokens in logs, evidence, tool definitions, or control plane responses.

5. **Control plane does not execute upstream actions**

* Control plane reports, explains, and orchestrates local operations.
* Execution happens only in runtime serve/proxy, under lockfile enforcement.

6. **Verification defaults must be non-brittle**

* Prefer user-facing locators and semantic assertions.
* Avoid full DOM dumps and OCR as primary truth.

---

## 3. Product shape: what Toolwright is [SHIPPED]

Toolwright is a **deterministic build system for agent capabilities**:

Inputs:

* captures (HAR/Playwright)
* configuration (allowed hosts, auth provider refs, redaction profiles)
* optional policy templates
* optional verification contract templates

Outputs:

* toolpack (tools + schemas + policy metadata)
* `toolwright.lock` (approved capability set)
* verification contracts and baseline evidence
* drift and verification reports for CI gating

Toolwright does not need a “meta MCP server” to be valuable. The primary value is the artifacts, the diff loop, and the verification runner.

---

## 4. Architecture [SHIPPED]

### 4.1 Core runtime engine

Keep the “single runtime package” approach. 
It is the cleanest way to guarantee parity between serve modes.

Package layout:

* `toolwright/core/runtime/`

  * `engine.py` execution orchestration + policy checks
  * `decision.py` decision trace models
  * `network_guard.py` allowlists, SSRF, redirect controls
  * `confirmation.py` confirmation requests and grants
  * `auth/` auth providers interface
  * `audit/` evidence bundle writing
  * `redaction.py` shared runtime redaction rules
  * `errors.py` canonical error codes

Acceptance criteria:

* same inputs yield same DecisionTrace in MCP serve and HTTP proxy
* conformance suite runs both frontends against shared fixtures

### 4.2 Control plane (reframed)

Rename “Meta server” to **Control Plane API** and lock its scope:

* Human and CI first
* Read-only introspection and orchestration of local operations
* No runtime execution against upstream services

Allowed:

* list toolpacks, diffs, approval states
* run verify, run drift
* produce explanations for denies and required confirmations
* produce suggested locators as drafts only

Not allowed:

* any tool that expands access
* any tool that grants approvals
* any tool that executes upstream calls

This preserves the useful parts from the earlier “meta” tooling list, without turning it into an escalation interface. 

### 4.3 Control Plane non-execution rule (new)

The Control Plane API must never execute upstream actions against enterprise systems. It may only:

* inspect artifacts
* run local verification and drift processes
* generate drafts and explanations

Any operation that contacts upstream systems must occur in:

* serve/proxy runtime
* sandboxed capture runner

This prevents the control plane from becoming an escalation surface.

---

## 5. Artifacts, models, and storage

### 5.1 Required artifacts [SHIPPED]

1. `toolpack/`

* `tools.json`
* `schemas/`
* `policy.meta.json` (risk, side-effect class, constraints)
* `scopes.json` (canonical scope objects)
* `verification/` (contracts and baselines)
* `digests.json` (canonical digests)

2. `lockfile/`

* `toolwright.lock` (signed approvals + constraints)
* `approvals/` (optional detached signatures)

3. `evidence/`

* `bundles/<bundle_id>.json`
* `attachments/` (redacted excerpts, UI evidence refs)

4. `reports/`

* `verify/<report_id>.json`
* `drift/<report_id>.json`

Storage requirements:

* local filesystem default
* pluggable backend interface later (S3 optional, not required for vNext) 

#### 5.1.1 Redaction Profiles [PLANNED]

Toolwright must support explicit **Redaction Profiles** that apply consistently across:

* captures (HAR/trace)
* runtime tool execution logs
* evidence bundles
* verification reports

A Redaction Profile is referenced by ID from:

* toolpack metadata
* lockfile policy
* verify/drift runs

**RedactionProfile fields**

* `profile_id` (string, stable)
* `description` (string)
* `rules[]` where each rule is:

  * `match_type`: `header | cookie | query_param | body_field | jsonpath | regex | url`
  * `match`: string
  * `action`: `remove | mask | hash | truncate`
  * `action_params` (optional) for `truncate_len`, `mask_style`, etc.
* `defaults`:

  * `mask_tokens: true`
  * `mask_auth_headers: true`
  * `mask_cookies: true`
  * `mask_pii: true`
* `pii_categories` (optional):

  * `email`, `phone`, `address`, `ssn`, `dob`, `bank_account`, `card_number`

**Required built-in profiles**

* `default_safe`
* `high_risk_pii`
* `debug_local_only` (explicit opt-in, never default)

**Hard rule**
No evidence bundle or report may be emitted without applying an explicit Redaction Profile.

### 5.2 Models

Keep `DecisionTrace` and `EvidenceBundle`, but tighten their intent:

#### 5.2.1 DecisionTrace (runtime output) [SHIPPED]

Purpose:

* deterministic allow, deny, or require confirmation
* machine-readable reasons for CI and audit

Fields:

* `decision_id`
* `action`: `allow | deny | require_confirmation`
* `deny_reason_code` (enum)
* `human_message`
* `agent_message` (structured)
* `matched_rules[]`
* `risk`: `{tier, factors[]}`
* `required_confirmation` (if any)
* `suggested_alternatives[]`

#### 5.2.2 EvidenceBundle (audit trail, retention-aware) [PLANNED]

Purpose:

* deterministic audit record of what ran, what policy applied, and what evidence was captured

**EvidenceBundle fields**

* `bundle_id`
* `created_at`
* `retention`:

  * `retention_days` (int)
  * `purge_at` (timestamp)
  * `legal_hold` (bool, default false)
* `actor`:

  * `type`: `human | ci | service | agent`
  * `id` (string)
* `tool_identity`:

  * `tool_id`
  * `tool_digest`
  * `toolpack_digest`
  * `lockfile_digest`
* `redaction_profile_id`
* `decision_trace_ref`
* `inputs_summary` (redacted)
* `outputs_summary` (redacted)
* `network_summary` (redacted)
* `attachments[]`:

  * `attachment_id`
  * `type`: `aria_snapshot | screenshot | dom_subtree | har_excerpt | trace_excerpt | api_response_excerpt`
  * `digest`
  * `storage_ref`
* `integrity`:

  * `bundle_digest`
  * `signature` (optional)

**Retention policy requirements**

* Default `retention_days` must be short (recommended: 7 to 30) unless explicitly overridden.
* High-risk flows default to shorter retention unless legal hold is set.
* Purge must delete attachments and derived artifacts, not just references.
* “Debug-local-only” evidence may never be uploaded to shared storage backends.

**CLI and API**

* `toolwright evidence purge --older-than <days>` must exist and be safe by default.
* `toolwright evidence hold --bundle <id>` requires explicit operator action.

#### 5.2.3 VerificationContract (new first-class) [ALPHA]

Purpose:

* an explicit contract of post-conditions that must hold after tool or workflow execution
* this is the thing you put in CI

Fields:

* `contract_id`
* `toolpack_digest`
* `targets[]`: tools or workflows
* `assertions[]` (multi-signal)
* `risk_tier`
* `flake_policy` (timeouts, retries, stabilization)
* `evidence_policy_ref`

---

## 6. Scopes vNext (comprehensive, credible) [SHIPPED]

### 6.1 Scope design goals

Scopes must be:

* conservative by default
* semantics-aware (not just HTTP verbs)
* reviewable in diffs
* enforceable at runtime
* tied to confirmations for high-risk actions

### 6.2 Scope object model

A scope is a structured object:

1. **Intent**
   Examples:

* `read`, `search`, `write`, `delete`, `admin`, `auth`, `payment`, `refund`, `export`

2. **Surface**

* API surface constraints:

  * host allowlist
  * method allowlist
  * path templates
  * query key allowlist/denylist
  * body key allowlist/denylist
  * content-type constraints
* UI surface constraints (optional):

  * allowed URLs and path patterns
  * allowed action types (click, type)
  * allowed target locators (role, label, testid)

3. **Risk tier**

* `low | medium | high | critical`

4. **Constraints**

* rate limits, concurrency caps
* value constraints (enums, regex, numeric bounds)
* field-level redaction constraints (deny sensitive outputs)
* identity constraints (which auth context)
* environment constraints (sandbox vs production)

5. **Confirmation requirements**

* none
* human confirmation
* break-glass token
* two-person review (optional later)

6. **Evidence**

* capture refs that justify scope surface
* verification contract refs that validate outcomes

### 6.3 Scope inference pipeline (how it actually works) [PLANNED]

Inference is staged and produces confidence, not magic.

Stage A: structural normalization

* method and path templates extracted
* endpoint clustering by shape and response patterns

Stage B: semantic classification
Use multiple signals:

* keyword and endpoint pattern heuristics (refund, role, delete, permission)
* observed state deltas (before/after reads when available)
* presence of idempotency keys and write-like headers
* status code patterns as weak priors

Stage C: side-effect detection
Do not guess. Detect where possible:

* API post-read after candidate write
* UI semantic change after action
* downstream events if configured

Stage D: conservative defaults

* if uncertain, classify higher risk
* if high risk and low confidence, require human review and confirmation

**Outputs (ScopeDraft)**
The compiler must emit `ScopeDraft` objects that are explicitly reviewable without relying on freeform LLM rationale.

`ScopeDraft` fields:

* `scope_id` (draft id)
* `intent` (enum)
* `surface` (API/UI constraints)
* `risk_tier` (enum)
* `constraints[]`
* `confirmation_requirement` (enum)
* `confidence` (0.0 to 1.0)
* `review_required` (bool)
* `explanation` (structured, no freeform reasoning):

  * `risk_reasons[]` (enum list)
  * `signals[]` where each signal is:

    * `signal_type` (enum)
    * `summary` (short string, templated)
    * `evidence_refs[]` (capture refs, request ids, before/after check refs)
  * `suggested_constraints[]` (structured)
  * `suggested_verification_assertions[]` (see VerificationContract assertions)

**RiskReason enum (minimum set)**

* `KEYWORD_DELETE`
* `KEYWORD_REFUND`
* `KEYWORD_PAYMENT`
* `KEYWORD_ROLE_PERMISSION`
* `KEYWORD_AUTH_SESSION`
* `ENDPOINT_NAME_SUGGESTS_ADMIN`
* `STATUS_CODE_WRITE_LIKELY` (weak)
* `OBSERVED_STATE_DELTA`
* `OBSERVED_UI_SUCCESS_STATE`
* `OBSERVED_DOWNSTREAM_EVENT`
* `SENSITIVE_FIELDS_PRESENT`
* `LOW_CONFIDENCE_DEFAULT_ESCALATION`

**SignalType enum (minimum set)**

* `PATH_PATTERN_MATCH`
* `BODY_FIELD_MATCH`
* `QUERY_KEY_MATCH`
* `HEADER_MATCH`
* `RESPONSE_SCHEMA_SENSITIVE`
* `BEFORE_AFTER_API_READ_DIFF`
* `ARIA_SUBTREE_DELTA`
* `WEBHOOK_EVENT_OBSERVED`
* `IDEMPOTENCY_KEY_PRESENT`

**Hard rule**
If confidence is below a threshold (default 0.7) and risk tier is `high` or `critical`, then:

* `review_required = true`
* `confirmation_requirement` must default to `human_confirmation`
* compilation must mark the tool as “unpublishable” until approved

### 6.4 Scope templates (deterministic presets)

Provide built-in templates:

* `readonly_minimal`
* `readonly_all`
* `write_with_confirmation`
* `admin_blocked`
* `no_sensitive_outputs`

These can be applied during mint or approval, but any broadening requires explicit approval.

### 6.5 Enforcement

Runtime enforcement checks:

* tool requires scope_id
* lockfile approves scope_id for this agent identity and environment
* constraints apply
* confirmation required gates writes as configured

Key rule:

* scope enforcement happens at execution time, not only compile time.

### 6.6 Scope change as drift (new)**

Drift detection must treat changes to scope semantics as first-class drift:

* Any change to `intent`, `risk_tier`, `surface` broadening, or constraint loosening is **broadening drift**.
* Broadening drift must fail CI by default.
* Narrowing drift may pass with warning, but must be recorded in the report.

Drift report must include:

* `scope_changes[]` with before/after canonical JSON and digests
* classification: `broadening | narrowing | neutral`
* required action: `approve_required | warn_only`

---

## 7. Lockfile vNext (the core artifact) [SHIPPED]

### 7.1 What the lockfile locks

`toolwright.lock` binds:

* toolpack digest
* tools and schemas digests
* scope objects digests
* risk tier and side-effect class per tool
* confirmation rules per risk tier or tool
* allowed hosts and egress policies
* verification contract digests required for publication of write tools (default)

### 7.2 Approval model

Approvals are explicit signer decisions over a diff:

* added tools
* modified tools and schemas
* new hosts or broadened patterns
* risk tier changes
* scope constraint changes
* verification contract changes

Rules:

* narrowing changes can be fast-path approved
* broadening changes always require explicit approval
* write/admin/auth surfaces require verification evidence by default

### 7.3 CI gates

CI should support:

* `toolwright diff --fail-on-broaden`
* `toolwright verify --contract <contract>`
* `toolwright drift --baseline <baseline>`

---

## 8. Verify vNext: multi-signal, assertion-based [ALPHA]

The prior spec had strong UI evidence modeling. Keep it, but explicitly subordinate it to “verification contracts,” not “agent-readable evidence” as the core deliverable. 

### 8.1 What verification is

Verification answers:

* “Did the intended post-condition hold?”
* “What evidence supports that?”
* “Is the system drifting?”

It is not:

* screenshot diffing as primary truth
* OCR-first
* “the agent said it succeeded”

### 8.2 Signals (default ordering)

1. API state assertions (post-reads, schema checks)
2. UI semantic assertions (role/label/testid)
3. UI ARIA snapshot of the minimal container proving the state
4. Network/event assertions (optional but supported)
5. Screenshot and DOM subtree for audit/debug, not default gating

This aligns with the earlier UI evidence policies and rules, but framed around reliability and CI gating. 

### 8.3 VerificationContract format [PLANNED]

A contract includes:

* target workflow or tool
* stabilization rules and retries
* evidence policy
* Assertions, which are typed and machine-checkable:

    * `api_state_assertion`

    * `endpoint_ref` (tool id or API read tool)
    * `expect`:

        * `jsonpath` or `field_path`
        * `op`: `equals | matches_regex | contains | gt | gte | lt | lte | exists`
        * `value` (optional)
    * `ui_assertion`

    * `locator: LocatorSpec`
    * `checks[]`:

        * `visible`
        * `enabled`
        * `has_text` (string/regex)
        * `has_role` (role)
        * `count_is` (int)
    * `aria_snapshot_assertion`

    * `within: LocatorSpec`
    * `snapshot_ref` (baseline id)
    * `mode`: `contains_minimal | equals_subtree` (default `contains_minimal`)
    * `event_assertion` (optional)

    * `type`: `webhook | queue | email_stub`
    * `expect`: structured conditions
    * `network_assertion` (optional)

    * `expect_request` or `expect_response` patterns (redacted)

#### 8.3.1 LocatorSpec

Verification contracts must use a structured locator format aligned with resilient UI testing practices. The locator resolution order is fixed and deterministic.

`LocatorSpec`:

* `strategy` (enum):

  * `role`
  * `label`
  * `text`
  * `testid`
  * `css` (last resort)
* `role` (when strategy=`role`)
* `name` (accessible name, optional but recommended)
* `label` (when strategy=`label`)
* `text` (when strategy=`text`)
* `testid` (when strategy=`testid`)
* `css` (when strategy=`css`)
* `within` (optional scoping):

  * another `LocatorSpec` defining the container
* `nth` (optional)
* `strict` (bool, default true)

**Selector priority rule (gold standard)**
Contracts SHOULD prefer:

1. `role` + `name`
2. `label`
3. `testid`
4. `text`
5. `css`

If a contract uses `css`, it must set `flake_policy` stricter defaults (more retries and stabilization).

### 8.4 Evidence policy defaults

Keep your existing UiEvidencePolicy ideas, but make them “debug and audit helpful,” not “the test truth.” 

Defaults:

* semantic assertions on
* ARIA snapshot on
* visible text tokens on
* container screenshot always for audit
* DOM subtree on failure
* OCR auto only when semantics unavailable
* full viewport and full DOM require explicit opt-in

### 8.5 FlakePolicy defaults (new)**

`FlakePolicy`:

* `timeout_ms`
* `retries`
* `stabilization_ms` (wait after action before checks)
* `screenshot_on_failure` (bool)
* `dom_subtree_on_failure` (bool)

Defaults:

* role/label/testid locators:

  * `timeout_ms = 10_000`
  * `retries = 1`
  * `stabilization_ms = 250`
* css locators:

  * `timeout_ms = 15_000`
  * `retries = 2`
  * `stabilization_ms = 500`

Hard rule:

* Full screenshot diffing may not gate by default. It is opt-in per contract.

---

## 9. Control Plane API (revised tool spec) [SHIPPED]

This is the updated list, removing any implication of agent privilege negotiation. It retains the useful orchestration and introspection tools. Compare to the prior meta tool spec. 

### 9.1 Introspection (read-only)

* `toolwright_list_toolpacks(filters?)`
* `toolwright_get_toolpack(toolpack_id)`
* `toolwright_list_tools(toolpack_id, filters?)`
* `toolwright_get_tool_details(tool_id)`
* `toolwright_get_capability_map(toolpack_id)` (intents, risk, dependencies)

### 9.2 Diff and approval (human/CI only)

* `toolwright_diff(toolpack_a, toolpack_b) -> DiffReport`
* `toolwright_approve(diff_ref, signer_ref, notes?) -> LockfileUpdate`

No “approve” tool should be exposed to agents. This API is for local operator tooling.

### 9.3 Verify and drift [PLANNED]

* `toolwright_verify_run(toolpack_id, contract_ref, options?) -> VerificationReport`
* `toolwright_verify_get(report_id) -> VerificationReport`
* `toolwright_drift_run(toolpack_id, baseline_ref) -> DriftReport`
* `toolwright_drift_get(report_id) -> DriftReport`

### 9.4 Explainability (read-only) [PLANNED]

* `toolwright_policy_dry_run(tool_id, params, context?) -> DecisionTrace`
* `toolwright_explain_denial(decision_id) -> DecisionTrace`

### 9.5 Draft-only helpers (never auto-executed) [PLANNED]

* `toolwright_ui_locator_suggest(evidence_ref, description) -> LocatorDraft`
* `toolwright_scope_suggest(capture_ref, guardrails) -> ScopeDraft`

Rules:

* suggestions are drafts
* any broadening requires approval
* no auto-execution of suggestions without passing verification

---

## 10. Discovery and "autonomous minting" (de-scoped for vNext) [PLANNED]

The prior spec spent a lot of surface area on agent-triggered discovery sessions. 
This rewrite moves discovery to “human-led by default,” with a safe path for later.

Current state clarification:

* Draft proposal queue tooling (`toolwright propose ...`) is shipped for human review workflows.
* Proposal bundle publication is shipped (`toolwright propose publish`) to convert reviewed proposal artifacts into runtime-ready tools/policy/toolsets and optional lockfile sync.
* Fully autonomous draft expansion (agent-triggered capture/mint/verify orchestration) is still planned and intentionally out of scope for current runtime behavior.

### 10.1 vNext: human-led discovery only

* humans run capture in sandbox
* `toolwright mint` compiles a draft toolpack
* `toolwright verify` attaches evidence
* `toolwright gate allow` publishes to lockfile

### 10.2 Autonomous Draft Expansion - Agent Tool Discovery and Drafting (after vNext)

Goal: Allow agents to **propose** new capabilities and generate **draft artifacts**, without any path to self-grant privileges.

**Key rule:** Agents may create *drafts*. Only humans/CI signers may **approve** and **publish**.

### 10.2.1 Trigger

A draft expansion is triggered when:

* runtime denies a tool call due to missing tool/scope/constraint, or
* verification fails due to missing assertions/evidence, or
* drift indicates an unmodeled new surface

Runtime emits a `MissingCapability` object:

* `reason_code`
* `attempted_action_summary`
* `suggested_capture_targets` (URLs/endpoints)
* `risk_guess` (conservative)
* `required_human_review: true`

### 10.2.2 Draft Expansion Outputs

A draft expansion produces a bundle:

1. **CapturePlan (draft)**

* target domains/hosts (must be allowlisted)
* URLs and navigation steps
* expected authentication context
* expected “success states” to verify
* strict time budget + rate limits

2. **ToolpackDelta (draft)**

* new/modified tools inferred from capture
* schema deltas
* scope deltas
* risk tier deltas

3. **ScopeDrafts (draft)**

* conservative scope objects with:

  * intent, surface, constraints, risk tier
  * confidence + reasons
  * `review_required` flags

4. **VerificationContractDelta (draft)**

* new/updated assertions for post-conditions:

  * API state assertions
  * UI semantic assertions (role/label/testid)
  * optional event assertions

5. **DiffReport**

* risk-classified diff suitable for code review

### 10.2.3 Execution model and trust boundary

Split operations into two lanes:

**Agent-visible (read-only / draft-only):**

* `toolwright_capabilities_list(toolpack_ref)`
* `toolwright_propose_expansion(missing_capability, constraints) -> DraftExpansionBundle`
* `toolwright_explain_denial(decision_id)`

**Operator/CI only (never agent-callable):**

* `toolwright_run_capture(capture_plan)` (sandboxed)
* `toolwright_mint_from_capture(capture_ref)`
* `toolwright_diff(toolpack_a, toolpack_b)`
* `toolwright_approve(diff_ref, signer_ref)`
* `toolwright_publish(lockfile_ref)`

### 10.2.4 Sandbox constraints (mandatory)

`toolwright_run_capture` must enforce:

* strict host allowlist and egress deny-by-default
* no credential exfiltration (redaction enforced)
* optional “sandbox environment only” requirement
* capped runtime, concurrency, and requests
* artifact redaction before persistence

### 10.2.5 Approval and publish

* Draft expansions cannot change production behavior until:

  * diff is reviewed
  * verification contracts pass in CI
  * lockfile is updated with explicit signer approval
* Any broadened surface (new host, new write/admin/auth intent) requires explicit approval.

### 10.2.6 Definition of “autonomous capability growth”

* The system supports **autonomous drafting** of new capabilities.
* The system does **not** support autonomous privilege escalation.
* Growth happens through: propose → capture → mint → verify → approve → publish.

### 10.2.7 Draft storage and runtime isolation (new)

Draft artifacts must be physically separated from published artifacts.

Directories:

* `.toolwright/drafts/<draft_id>/`

  * `capture_plan.json`
  * `toolpack_delta/`
  * `scope_drafts.json`
  * `verification_contract_delta.json`
  * `diff_report.json`
  * `evidence_refs.json`
* `.toolwright/published/`

  * published toolpack and lockfile references

Rules:

1. Runtime and serve modes MUST ignore `.toolwright/drafts/` entirely.
2. Only `toolwright gate allow` may promote drafts to published state.
3. Promotion is a copy operation into `.toolwright/published/` plus lockfile update.
4. Drafts may be committed to git, but must not be referenced by default configs.
5. Provide `.gitignore` guidance:

   * recommend ignoring raw traces and attachments by default
   * allow committing contracts and diffs if desired

**Approval promotion contract**
`toolwright gate allow --draft <draft_id>` must:

* validate draft artifacts are internally consistent
* run `verify` for any new write/admin/auth surfaces (or require an explicit bypass)
* produce a lockfile update with signer metadata
* emit a promotion report with digests

---

## 11. Auth providers (keep, but treat as operational reality) [PLANNED]

Keep the auth provider interface and implementations. 
This is important because tool supply chain without auth reliability is fake.

Rules:

* providers never emit secrets into logs or evidence
* runtime stores only references and redacted shapes
* safe logging mode rejects accidental token printing patterns

### 11.1 Token handler mode (BFF integration) (new)

Toolwright must support an auth integration mode where agents never see refresh tokens.

Mode: `token_handler`

* runtime calls a local or enterprise-provided backend service that:

  * holds refresh tokens
  * issues short-lived access tokens or session cookies for execution
* tool execution uses only:

  * opaque session references
  * short-lived access tokens scoped to the tool call

Requirements:

* no refresh tokens in logs, evidence, toolpack, or agent-visible outputs
* audit records reference auth context by opaque id only
* token handler endpoints are allowlisted and isolated

Optional later:

* support token exchange patterns if enterprises already have them, but do not require it for vNext.

---

## 12. CLI (updated and aligned) [SHIPPED]

### 12.1 Core commands

* `toolwright init` -- initialize project
* `toolwright mint <url>` -- capture + compile in one shot
* `toolwright diff` -- risk-classified change report
* `toolwright gate sync|allow|block|check|status|snapshot|reseal` -- approval workflow
* `toolwright serve` -- MCP server (stdio) under lockfile enforcement
* `toolwright run` -- execute toolpack with policy enforcement
* `toolwright drift` -- detect capability surface changes
* `toolwright verify` -- run verification contracts
* `toolwright demo` -- offline governance proof loop

### 12.2 More commands

* `toolwright capture import|record` -- traffic capture from HAR, OTEL, OpenAPI, or browser
* `toolwright workflow init|run|replay|diff|report|pack|export|doctor` -- verification workflows
* `toolwright auth login|status|clear|list` -- auth profile management

### 12.3 Advanced commands (behind `--help-all`)

* `toolwright compile`, `toolwright bundle`, `toolwright lint`, `toolwright doctor`, `toolwright config`
* `toolwright inspect`, `toolwright enforce`, `toolwright migrate`
* `toolwright confirm`, `toolwright propose`, `toolwright scope`, `toolwright compliance`, `toolwright state`

---

## 13. Testing and CI requirements (tightened)

### 13.1 Golden fixtures

* deterministic toolpack generation from:

  * HAR fixture
  * Playwright trace fixture
  * optional OpenAPI fixture
* golden digests for core artifacts

### 13.2 Runtime parity suite

* MCP serve and HTTP proxy produce identical DecisionTrace for the same request.

### 13.3 Security regression suite

* SSRF blocked
* redirect to disallowed hosts blocked
* token leakage tests
* malicious tool description injection cannot alter policy evaluation
* lockfile broadening requires approval

### 13.4 Verification reliability suite

* assertion-based checks pass under minor DOM churn
* screenshot diffs never gate unless explicitly enabled
* OCR never runs in auto when semantic signals are available
* redaction is enforced across tokens, dom subtree, screenshots

---

## 14. Delivery plan (re-ordered for the wedge)

Phase 1: Mint + lockfile loop

* deterministic mint
* diff and risk classification
* approve produces signed lockfile
* serve enforces lockfile

Phase 2: Verify contracts

* contract format
* multi-signal assertions
* structured reports and evidence bundles
* CI templates

Phase 3: Drift gates

* drift report
* fail rules (write/admin/auth drift fails by default)
* “contract broke” is first-class drift

Phase 4: Control plane API (read-only + orchestration)

* introspection
* policy dry-run and deny explanations
* verify and drift orchestration

Phase 5: Optional indexing and optional discovery runner

* only after wedge is proven and stable

---

## 15. Updated user stories

### Story 1: Staff engineer operationalizes a legacy app for safe agent use

Persona:

* staff engineer, owns an internal tool

Flow:

1. Capture a sandbox workflow with Playwright.
2. Run `toolwright mint` to produce a draft toolpack.
3. Run `toolwright verify` using a verification contract:

   * API post-condition (state changed)
   * UI semantic assertion (role/label)
   * optional webhook fired
4. Review `toolwright diff`, then `toolwright gate allow`.
5. Serve toolpack under lockfile enforcement.
6. CI runs `toolwright drift` nightly. If drift breaks contract, deployment blocks.

Outcome:

* least privilege via scopes
* write actions require confirmation
* drift is caught before production incidents

### Story 2: Platform team standardizes agent onboarding across 50 internal services

Persona:

* platform lead tasked with agent rollout

Flow:

* teams mint toolpacks from captures
* lockfile approval becomes standard code review
* verification contracts become required CI checks for write tools
* drift gates prevent silent breakage

Outcome:

* “agent onboarding” becomes a deterministic pipeline, not a bespoke project.

---

## 16. Definition of Done for vNext (replacing “Full Meta”)

You are “done” when:

1. A clean machine can run:

* mint → diff → approve → serve → verify → drift
  in a single repo, deterministically.

2. Verification is reliable:

* minimal flake
* clear failure reasons
* reproducible evidence

3. Drift is meaningful:

* contract breaks fail CI
* write/admin/auth drift fails by default

4. No escalation channels exist:

* no agent tool requests more privileges
* no in-protocol approval interface exposed to agents
