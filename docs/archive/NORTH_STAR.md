## North Star

Toolwright is a capability supply chain for agents: **mint** tool surfaces from evidence, **diff** them, **gate** them with signatures, **run** them fail-closed, **detect drift**, and **verify outcomes**. Your own docs already lock that pipeline as the v1 outcome: `mint -> diff -> gate -> run -> drift -> verify`.  

Two non-negotiables that make the whole thing real:

* **Fail-closed runtime**: “if it’s not in the lockfile, it’s blocked.”  
* **Trust boundary**: agents can draft, humans approve; control plane is read-only and never executes upstream actions.   

Everything below is a concrete implementation plan that gets you:

* v1: shippable wedge with a real wow moment and low friction.
* full vision: “plug and play” capture + auth + drafting automation that still cannot silently escalate.

---

## The user experience you should optimize for

### The <5 minute wow moment (realistic)

You already have the right move: **offline demo** first-run, no browser, no network. `pip install toolwright` then `cask demo`. 
That is how you meet the 5-minute constraint without lying about Playwright downloads.

### The 15 to 30 minute “real mint” moment (until you add a container runner)

A real capture workflow needs browser automation and often MFA. Your README already says “full install” includes Playwright + browser install. 
Do not claim this is <5 minutes today. Make it brutally explicit.

### The full-vision <5 minute “real mint” moment

You get that only by shipping one of these:

1. **Prebuilt container runner** with browsers included (pull image, run `cask mint ...`).
2. **Remote capture runner** (hosted browsers) with a local control plane and strict egress constraints.
3. **HAR-only onboarding** (export from DevTools, `cask capture import`, then compile). This can be <5 minutes but less magical.

---

## v1 spec (what “done” means)

### v1 promise

Ship the deterministic governance wedge end-to-end, exactly as your release lock says. 

### v1 command surface

Flagship: `init`, `mint`, `diff`, `gate`, `run`, `drift`, `verify`, `mcp serve`, `mcp inspect`. 
Compatibility aliases and lockfile resolution order must stay stable. 

### v1 security and governance contracts

Must hold in tests and docs:

* runtime requires approved lockfile by default; pending is rejected. 
* approvals are Ed25519-signed with signer identity and key management. 
* network guards: scheme restrictions, DNS/IP checks, redirect hop validation. 
* secrets never enter agent-visible surfaces; auth state is local-only.  

### v1 verification contract

`cask verify` modes and provenance rules must match the spec.  

### v1 limitations you must state up front

Don’t hide these; they keep you honest and credible:

* MFA/passkeys/device trust: interactive reauth required. 
* “autopilot” is deterministic probe automation, not unrestricted browsing. 
* provenance is heuristic ranking, not a formal proof. 
* no bypass claims for MFA/anti-bot.  

---

## Architecture spec (v1 + full vision)

### 1) Core artifacts (the “supply chain”)

These must be deterministic, diffable, and stable.

* **Capture**: HAR / Playwright trace / WebMCP discovery. (You already claim all three). 
* **Toolpack**: tools + schemas + policy metadata.
* **Pending lockfile**: produced by mint, never runtime-authoritative by default. 
* **Approved lockfile**: signed approvals, runtime source of truth. 
* **Diff report**: risk-classified PR-friendly markdown. 
* **Evidence bundles**: JSONL with digests and redaction support. 
* **Verification report**: machine-readable result with exit codes. 

### 2) Storage contract

Lock this early and never “helpfully” change it.
Your README already defines canonical root locations including local-only auth profiles and drafts ignored by runtime. 
That is exactly what prevents draft automation from becoming a privilege escalation path.

### 3) Runtime vs control plane boundary

* Runtime is where upstream calls happen, under lockfile enforcement. 
* Control plane is read-only introspection + local orchestration, not an execution surface. 
* Threat model explicitly defends against unapproved capability expansion and lockfile bypass in safe mode. 

### 4) MCP integration targets

Support the MCP client ecosystem by keeping your server “boring”:

* stdio is baseline; Streamable HTTP is optional later, but follow the MCP transport and auth specs if you do. ([Model Context Protocol][1]) ([Model Context Protocol][2])
* if you offer OAuth, implement PKCE and proper metadata and token handling per the MCP authorization spec. ([Model Context Protocol][2])

---

## Auth system spec (seamless, but honest)

### Design goals

* One-time login, reusable profile for capture. 
* Never leak secrets into artifacts, logs, MCP tool schemas, or control plane responses. 
* Reauth flow that is interruptible and resumable.

### Auth profile types (v1)

1. wright storageState)**

   * `cask auth login --profile X --url ...`
   * store at `<root>/:contentReference[oaicite:40]{index=40}tate.json`. 
   * Treat as a secret. Playwright storage state contains cookies and local storage, so it must be handled like credentials and not committed. ([Playwright][3])

2. **Header token profile**

   * Sourc   - Never write raw token to disk.
   * Runtime and capture read token via provider interface only.

3. **OAuth interactive profile (full vision, optional in v1)**

   * Implement per MCP authorization spec when you expose HTTP transport and need delegated auth. ([Model Context Protocol][2])
   * Support device-code flow for CLI friendliness.

### Reauth and MFA (how it works without being miserable)

* v1: admit “guided interactive reauth required.” 
* Implementation:

  * capture runner detects auth failure signals (401/403, redirects) and emits `AuthNeeded`.
  * the CLI pauses capture, opens a browser window with a clear prompt: “Complete MFA, then click Continue”.
  * capture resumes and re-saves storage state.
* Full vision improvement:

  * add “persistent contexon it exists) for hard apps. 
  * add session health checks and expiry prediction (cookie max-age, token exp).

### Auth risk mitigations

* **Secret leakage**: enforce redaction before writing evidence. 
* **Token replay**: confirm tokens are signed, single-use, and request-bound. 
* **IdP allowed_hosts split (already in release gates). 

---

## Capture system spec (agent-friendly, robust)

### Capture inputs (v1)

* HAR import
* Pscovery (`navigator.modelContext`) 

### Determilicitly say autopilot is deterministic probe automation. Keep it that way. on:

* Autopilot is a **playbook generator**, not a freeform browser agent.
* It outputs a `playbook.yaml` (draft) plus:

  * target URLs
  * “success states” (UI API host candidates
* Then it runs that playbook with strict budgets.

### Playbook spec (v1)

Your verification systemsertions. 
Implementation requirements:

* Prefer robust locators: role, label, testid.
* Avoid OCR as truth. Your architecture already calls this out. 

### Open source leverage for capture

* **mitmproxy2swagger** is useful inspiration for traffic-to-OpenAPI generation from captures. Use it as a re and spec generation, not as a drop-in core. ([GitHub][4])

---

## Compile pipeline spec (turn traffic into “good tools”)

### Goals

* e inputs -> same artifacts and digests. 
* Correct tool surfaces: stable IDs, accurate schemas, safe defaults.
* Generate **scope drafts** that actually help the user find the right APIs.

### Step-by-step compile

1. **Normalize requests**

   * canonicalize URL (scheme, host, path template)
   * normalize headers (drop volatile)
   * detect auth headers and mark as sensitive

2. **Cluster endpoints inethod, host, path template)

   * split by content-type and semantic “intent hints” (search-like vs detail vs mutation)
   * compute operation fingerprint from stable fields

3. **Schema inference**

   * infer JSON schema from response bodies (sample set)
   * tag fields with stability score (frequency, optionality)
   * mark unknown blobs as `additionalProperties: true` but isolate

4. **Risk classification**

   * write/delete/money actions flagged, require explicit approval in lockfile and explicit toolset selection. 

5. **Generate tool definitions**

   * each tool includes:

     * input schema (query/path/body)
     * output schema
     * constraints (allowed hosts, rate limits)
     * guardrails metadata (risk tier)

6. **Generate pending lockfile**

   * default toolset is readonly (per compatibility matrix defaults). 

---

## Scopes featriendly)

Your ownership model is correct:

* `scopes.suggested.yaml` is generated.
* `scopes.yaml` is user-owned and authoritative.
* merge proposes diffs and never overwrites silently. 

### What a “scope” must represent

A scope is not “an endpoint list”. It is an intent-labeled

* capture focus
* tool surface reduction
* safer runtime allowlists
* better “missing capability” suggestions

### ScopeDraft algorithm (v1)

Input: compiled operations + capture evidence.
Output: scope drafts with:

* confidence score
* ran
  Your README already promises confidence scoring and risk reasons. 

Heuristics that actually work:

* **Search-like detection**: repeated requests as user types, query param names like `q`, `query`, `term`, `search`, or payload fields that mirror typed text.
* **List/detail pairing**: list response includes ids, then subsequent calls fetch details by id.
* **Mutation detection**: non-idempotent methods, or GETs with state chaCSRF patterns).

---

## Governance workflow spec (diff, gate, CI)

### Diff

* Must be deterministic and risk-classified, PR-friendly.  

### Gate

* Ed25519 signatures. 
  Ed25519 is standardized in RFC 8032. ([RFC Editor][5])

### CI gating policy

* You already define CI integration patterns and exit codes. 
* Keep “unknown provenance budget” as a hard gate default (20%) and make it configurable, but nen source leverage for diffing
* t breaking changes in generated OpenAPI and fold that into your drift and diff reports. ([GitHub][6])

---

## Runtime enforcement spec (fail-closed + safe networking)

### Run default path for v1. 

* `enforce` HTTP proxy optional path.

### Default deny

Runtimequires explicit allow. 

### Network guard (SSRF, DNS rebinding, redirects)

You already claim this as shipped. 
Make it correct by following OWASP SSRF guidance:

* allowlist hosts
* block private/metadata IP ranges
* re-resolve DNS on redirects and validate each hop
* restri([OWASP Cheat Sheet Series][7])

### Confirmation tokens

* Signed, single-use, request-bound. 
  Implemetion to (tool_id, request_fingerprint, lockfile_hash, toolset, expiry).

---

## Verifics your “trust closer”)

Your verification spec is already solid; implement it ruthlessly:

* modes: contracts/replay/outcomes/provenance/all 
* provenance goal: map UI output to ranked API/tool candidates with evidence 
* taxonomy includes websocket/sse/local_state so you can return `unknown` honestly. op_k=5, min_confidence=0.70, capture_window_ms=1500, unknown_budget=20% 

### Provenance scoring signals (v1)

Deterministic, explainable scoring:

* timing overlap with assertion window
* content match (text fragments)
* shape match (JSON schema compatibility)
* repg)
* request chain adjacency (list -> detail)

If non-HTTP dominates, return ` 

---

## Agent-driven  (full vision, safely)

You already have the correct doctrine:

* “Agents draft, humans approve.”
* Draft expansion gets triggered by runtime denies, verify failures, or drift. 

### Full vision: Draft Expansion Bundle (what the agent produces)

Match your architecture:

* CapturePlan (draft)
* ToolpackDelta (draft)
* ScopeDrafts (draft)
* VerificationContractDelta (draft)
* DiffReport  it tools into two lanes exactly as your architecture says:
* Agent-visible: list, explain, propose (draft-only)
* Operator-only: run capture, mint from

### Sandbox constraints (mandatory for any autonomos the right constraints:

* strict host allowlist, deny-by-default egress
* capped runtime, concurrency, requests
* artifact redaction before persistence 

---

## Risk register (p# 1) SSRF and egress abuse

Risk: agents or compromised tool defs trick runtime into hitting metadata endpoints or internal services.
Mitigation:

* runtime URL scheme allowlist, host allowlist, DNS resolution + IP rangdation 
* implement OWASP SSRF controls fully, including DNS rebinding defenses ([OWASP Cheat Sheet Series][7])

### 2) Secret leakage through artifacts, logs, MCP responses

Risk: tokens/cookies end up in toolpack, ev plane.
Mitigation:

* “secrets never enter agent-visible surface” as a hard invariant 
* treat Playwright storage state as a secret, never commit ([Playwright][3])
* enforce redaction pipeline before persistence (your threat model says you defend this) FA, passkeys, device trust)
  Risk: users churn because auth is annoying.
  Mitigation:
* be honest: interactive reauth is required 
* build reauth pause/resume as first-class UX
* full vision: persistent context fallback and token-provider adapters

### 4) False confidence from provenance

Risk: user thinks you “proved” causality; you really ranked candidates.
Mitigation:

* keep `pass/unknown/fail` 
* display “why” signals in report; never hide low confidence

### 5) Silent privilege escalation via drafts

Risk: agent-generated drafts end up being used as runtime truth.
Md under root and ignored by runtime 

* pending lockfiles are not runtime-authoritative unless explicit unsafe mode rs bounce on install friction (Playwright download)
  Risk: “wow moment” fails.
  Mitigation:
* keep the no-network demo path as primary first-run 
* full vision: container runner or remote capture runner to make “real mint” fast

---

## Open source projects to steathem)

1. **mitmproxy2swagger**
   Use for ideas on traffic clustering -> OpenAPI generation. ([GitHub][4])

2. **oasdiff**
   Use for spec diffing and breaking-change classification in drift and PR reports. ([GitHub][6])

3. **OW**
   Treat as requirements for network_guard correctness. ([OWASP Cheat Sheet Series][7])

   Treat storage state as a secret, implement safe handling and .gitignore defaults. ([Playwright][3])

---

## Implementation plan (v1 to full vision)

###ce” (1 to 2 days)
Goal: no doc lies, no surprising defaults.

* Make README + user guide the canonical workflow surface (you already state this). 
* Add “Real mint takes longer due to browsers/MFA” as explicit text near quickstart.
* Ensure `cask demo` is always the first suggested command. 

Acceptance:

* fresh venv: `pip install toolwright` then `cask demo` succeeds.
* packaging smoke in CI stays green. 

### Phase 1: v1 hardening pass (1 to 2 weeks)

Goal: the wedge is unbreakable and boring.

1. **Runtime fail-closed**

   * enforce approved lockfile search order and reject pending by default 

2. **Network guard correctness**

   * write adversarial tests for redirect hops, DNS rebinding, private IP blocks
   * align with OWASP SSRF checklist ([OWASP Cheat Sheet Series][7])

3. **Auth profile safety**

   * guarantee auth state is local-only and excluded from bundles 
   * add `cask auth doctor` that checks file perms and warns lou  - make diffs include: host changes, write surface changes, scope changes, schema deltas, verify deltas
   * keep `--format github-md` stable *Verify and provenance**
   * implement full report contract, status rules, exit codes olds from docs 

Acceptance:

* “golden path” is copy/paste runnable from README on a clean machine, and runtime blocks unapproved actions by default 

### Phase 2: Make capture feel good (2 to 4 weeks)

Goal: get real users to mint from real sites without hating you.

* Ship **deterministic autopilot** that only generates playbooks + UI assertions drafts, then runs them. 
* Add “pause for reauth” UX and resume capture. 
* Improve scope drafts so userslist/detail” flows.

Acceptance:

* A “typical” SPA can be minted with one login and one capture run.
* `scopes merge` never overwrites user scopes silently. 

### Phase 3: Agent drafting (safe) (4 to 8 weeks)pansions without any approval path.

* Implement the Draft Expansion Bundle exactly as your ar
* Expose only readto agents.
* Store drafts under `<root>/drafts/...` and guarantee runtime ignores them. 

Acceptance:
-nDraft + ToolpackDelta + VerificationContractDelta, but cannot change runtime behavior until a human signs. 

### Phase 4: Full plug-and-play (the real “<5 min real mint”) (8 to 16 weeks)

Pic-to-end:

1. **Container runner** (simplest to shiuilt image with browsers

   * `cask mint --runner docker ...`

2. **Remote capture runner** (best UX, more security work)

   * sandboxed hosted browser
   * strict egress, no credential exfiltration, redaction enforced 

3. **OAuth token handler BFF** (enterprise-ish)

   * you already have “token handler BFF” planned as a runtime adapter concept 
   * implement it only after you havt critique you should accept
     If you chase “fully autonomous browsing to discover hidden APIs” in v1, you will lose. It explodes scope, incown threat model says it is out of scope. 
     The winning path is what you already wrote: deterministic drafting + diff + signatures + fail-closed runtime. CLI help output for `cask mint` and `cask auth` and I’ll turn this spec into a concrete “exact flags, exact defaults, exact error strings” contract that you can hard-gate in tests.



[1]: https://modelcontextprotocol.io/docs/concepts/transports "https://modelcontextprotocol.io/docs/concepts/transports"
[2]: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization "https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization"
[3]: https://playwright.dev/docs/auth "https://playwright.dev/docs/auth"
[4]: https://github.com/alufers/mitmproxy2swagger "https://github.com/alufers/mitmproxy2swagger"
[5]: https://www.rfc-editor.org/info/rfc8032 "https://www.rfc-editor.org/info/rfc8032"
[6]: https://github.com/oasdiff/oasdiff "https://github.com/oasdiff/oasdiff"
[7]: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html "https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html"


---

## 0) Non-negotiable reality checks (so the plan stays feasible)

1. **“Capture any kind of auth/login” is not literally achievable.** Passkeys, device trust, CAPTCHA, and some MFA flows cannot be automated and should remain explicitly out-of-scope (and your threat-model doc already says no bypassing). 
   **Feasible target:** “Guided human login + session capture where possible, fast reauth when it expires, and clean failure modes when it can’t be captured.”

2. **The 5-minute wow moment cannot depend on Playwright browser installs.** Browsers are a big install step.
   **Feasible target:** wow in 5 minutes via **offline demo + MCP serve**; then “real site capture” in 10–20 minutes.

3. **“Find the search API even if it’s not named intuitively” is feasible only if you treat it as** deterministic feature extraction + conservative confidence + review gates, exactly like your scopes model intends. 

---

## 1) The North Star product (full vision)

**Toolwright becomes the capability supply chain for agents:**

* Capture observed behavior (web, APIs, OpenAPI, WebMCP).
* Compile it into deterministic artifacts (tools, schemas, scopes, dependency graph).
* Show a risk-ranked diff.
* Gate via signed approvals.
* Enforce at runtime (fail-closed).
* Detect drift.
* Verify outcomes and provenance.

This is already the canonical story in your docs and release plan, and the CLI “golden path” is the backbone.   

---

## 2) Best first ICP (and why)

### ICP pick: “Agent power users who ship automations in repos”

Think: builders using Cursor / Claude Code / Windsurf, plus small teams who already live in GitHub PRs and CI.

Why:

* They immediately “get” diff + lockfile governance (your wedge). 
* They can install a CLI and run it without procurement.
* They will share demos publicly if you give them a ridiculous wow moment.

### Viral wedge inside that ICP: “Read-only ecommerce intelligence”

Not “botting checkout.” Just:

* Identify the site’s search and product-detail data flows.
* Mint a safe, read-only MCP toolset.
* Let an agent query products reliably.

This is **highly legible in a 60-second demo** and aligns with your scope templates and risk tiers (block write/payment/admin by default). 

---

## 3) The 5-minute wow path (what the user experiences)

### Goal

From install to “agent calls a governed tool through MCP” in under 5 minutes.

### The path (must be copy/paste, no surprises)

1. `pip install toolwright`
2. `cask demo` (offline, deterministic)
3. `cask mcp serve --toolpack <demo>` (or `cask serve`)
4. User adds one generated MCP config to their agent client (Cursor/Claude)
5. Agent successfully calls a tool, and Cask prints DecisionTrace proof

This lines up with your intent: demo exists to avoid Playwright friction, MCP configs are generated by init, and runtime is fail-closed by default.   

### What the wow should feel like

* The agent calls a tool.
* Cask shows: allowed because lockfile + scope digest + host allowlist.
* Any disallowed attempt returns a structured “MissingCapability” object (not a vague error), which can feed the draft loop later. 

---

## 4) v1 spec (ship-ready scope)

v1 is not “everything.” v1 is the governance wedge end-to-end, with a clean UX and honest constraints. 

### v1 deliverables (concrete)

1. **Golden path that works exactly as docs say**
   `mint -> diff -> gate -> run -> drift -> verify` 

2. **Auth profiles for capture-time only (no runtime tokens yet)**

* `cask auth login/status/clear/list`
* `cask mint --auth-profile X`
* Explicit rule: auth state excluded from toolpacks/bundles/evidence/baselines 

3. **Scopes ownership + merge**

* `scopes.suggested.yaml` generated
* `scopes.yaml` authoritative
* merge proposes diffs only  

4. **Verify engine with provenance mode**

* contracts/replay/outcomes/provenance/all 
* defaults: `top_k=5`, `min_confidence=0.70`, `capture_window_ms=1500`, unknown budget 20% 

5. **Runtime safety**

* fail-closed lockfile enforcement by default 
* egress restrictions + DNS/IP checks + redirect hop validation 
  These map to standard SSRF defenses recommended by OWASP.

6. **Signed approvals**

* Ed25519 signer identity + trust store + rotation + revoke 
  Ed25519 is a standard scheme (RFC 8032). ([GitHub][1])

---

## 5) Ecommerce dogfooding pack (v1.1, but design now)

### The “Cask Commerce Pack” (read-only by default)

You want a preset scope pack that reliably finds:

* search results flow
* product detail flow
* inventory/price fragments
* pagination

And that reliably blocks:

* cart
* checkout
* payment
* account/admin

This is exactly what your scopes contract is meant to express (intent, surface constraints, risk, constraints, confidence, review state). 

### Deterministic inference pipent)

Your architecture already defines staged inference with confidence, conservative fallback, and review-required gating. 
Implement it like this:

**Sta
Represent every observed call as an “operation object”:

* request: host, method, path template, query keys, content-type, body shape fingerprint
* response: status, content-type, response shape fingerprint, pagination indicators
* context: capture step id, timestamp, initiator hints if available

**Stage B: Clustering**
Group calls by:

* (host, path template, method) + body/response fingerprints
  This is how you handle non-intuitive endpoints and GraphQL/RPC-ish patterns without pretending the URL name is meaningful.

**Stage C: Feature extraction (deterministic)**
Signals that strongly identify ecommerce search/product reads:

* query keys: `q`, `query`, `search`, `term`, `page`, `cursor`, `sort`, `filter`
* response shape: list of product-like objects, fields like `title`, `handle`, `sku`, `price`, `currency`, `image`
* pagination: `pageInfo`, `nextCursor`, `totalCount`, `hasNextPage`
* request frequency: triggered by typing/search submit vs background refresh
* content overlap: response tokens overlap with DOM text in the capture window (privacy-preserving hashes, not raw strings)

**Stage D: Label rules + confidence**
Output:

* intent label: `search`, `read`, `export`, `auth`, `payment`, etc.
* risk tier (conservative)
* confidence score
* `review_required` flag
* structured reasons and evidence refs (your spec explicitly wants no freeform rationale). 

**Hard safety rule**
If confideh/critical:

* `review_required: true`
* default confirmation requirement must be human confirmation
* tool is unpublishable until approved 

### Preset scope templates (shicalls these out explicitly. 

Implement at least:

* `commercch + product read only, strict host allowlist
* `commerce_readonly_all`: broader read-only (still blocks export-like bulk)
* `commerce_block_payments`: explicit deny patterns for payment/refund/checkout/cart/admin/auth mutation

---

## 6) Auth UX (make it “seamless” without lying)

### v1: capture-time auth profiles only

This is already in your changelog. 

**UX requirements**

* `cask aut:contentReference[oaicite:34]{index=34}ain>` launches a guided browser session.
* On success, store `storage_state.json` locally with tight permissions (you’re already doing 0600). 
* Never include it in toolpacks/eady your rule). 
  Playwright storage state containlaywright’s docs warn it should be treated as sensitive.

**Reauth flow (v1)**

* Detect likely auth failure during capture (401/403, redirect to login) and pause with a “reauth needed” prompt. 
* Run `cask auth login --profile record an “auth regained” proof step (an authenticated endpoint returning 200, or a known logged-in UI assertion).

### Full vision: runtime token handling (v2)

Your README calls runtime token handler BFF as planned, with TokenProvider protocol defined. 
This is where you support:

* lows
* refresh token lifecycle
* rotation and revocation

If you do remote MCP over HTTP, align with MCP’s authorization and transport specs rather than inventing your own. ([GitHub][2])

---

## 7) Dependency mapping (parents/children) that is defensible

You want “parents and children” to help users understand flows and blast radius.

### Do not claim causal truth

Claim this instead:

* temporal adjacency
* identifier propagation
* repeated co-occurrence across runs

### Implementable algorithm (deterministic)

For each capture run:

1. Partition traffic by playbook step boundaries and time windows.
2. Build candidate edges A -> B if B occurs within N ms after A in the same step window.
3. Score edges with:

   * ID propagation: tokens from response A appear in request B (IDs, cursor, CSRF)
   * consistent ordering across repeated captures
   * same initiator when you can obtain it
4. Emit:

* `capability_graph.json` (nodes: operations/tools, edges: typed dependency, score, evidence refs)
* expose graph deltas in `diff` as “blast radius context”

This integrates cleanly with your “diff is control plane” philosophy. 

---

## 8) Verification and provenance (make it a product, not a checkbox)

You alre- playbooks + UI assertions required for provenance mode 

* strict status rules and defaults 

### What to add y-as-receipt” output**

After a tool was asserted

* what candidate API calls likely caused it (ranked)
* confidence and reasons
* redacted evidence bundle refs

This is the “oh shit” moment: the system doesn’t just run tools, it proves likely causality and shows receipts.

**B) CI gates that matter**
Your CI policy and drift integration already treat contract failures as breaking (exit 2). 
Double down:

* For any tool classified as write/payment/admin: verification contrachitecture implies this). 
* For read-only ecommerce: provenance unknown budget applies, but block if unknown-

## 9) Agent-driven capture drafting (robust, safe, actually useful)

Your architecture very explicitly splits:

* agent-visible read-only/draft-only tools
* operator/CI-only capture/mint/approve/publish tools 

### The only safe “autonomous” story

Agents can:

* propose missing capability
* drafts
* draft verification assertions

Humans/CI must:

* execute capture
* approve/publish

This is your manifesto’s “agents draft, humans approve” principle. 

### Implementation details that make it robust

When runtime denies an action:

* em reason code

  * attempted action summary
  * suggested capture targets (URLs/domains)
  * conservative risk guess
  * `required_human_review: true` 

Then `cask propose create`:

* produces a DraftExpansionBundle stored under `.cask/dion (runtime ignores drafts). 

To make this *feel magical*:

* include a “one-click PR bundle” output:

  * diff mar
  * suggested verification assertions yaml
  * capture plan json
    So the human’s job is reviewing, not writing paperwork.

---

## 10) Open source to steal ideas from (and where it fits)

These are pragmatic leverage points that match your pipeline:

### Capture and traffic to OpenAPI

* **mitmproxy** as an optional capture adapter (intercept HTTP flows) ([DevNet Expert Documentation][3])
* **mitmproxy2swagger** to translate captured flows into OpenAPI-like specs ([GitHub][4])
  Use case: when Playwright is too heavy or UI automation is fragile.

### HAR parsing

* **haralyzer** (Python HAR parsing) can speed up your HAR adapter and normalization ([OWASP][5])

### OpenAPI diffing and breaking-change classification

* **oasdiff** as inspiration or a drop-in for spec diffs and breaking change heuristics ([GitHub][2])

### Contract testing

* **Schemathesis** for property-based testing against OpenAPI (great for “verify contracts” in API-only contexts) ([OWASP Cheat Sheet Series][6])

### JSON schema inference

* **genson** (schema from examples) is useful for response-shape fingerprinting and quick schema drafts ([OWASP Cheat Sheet Series][7])

You do not need to adopt all of these. But each maps cleanly to a stage in your pipeline and can reduce build time.

---

## 11) Roadmap you can actually execute

### Phase 0: Lock the 5-minute wow (now)

Acceptance criteria:

* `cask demo` works offline
* `cask serve` exposes MCP tools
* user guide steps match behavior exactly
* DecisionTrace shows allow/deny receipts

This is already aligned with your release gate doctrine. 

### Phase 1: Ecommerce read-only dogfood pack (v1.1)

Acceptance criteria:

* One command that guides the user through:

  * optional auth login (only if needed)
  * capture a search + product-detail flow on a chosen site
  * mint toolpack
  * propose scopes
  * run `scopes merge`
  * generate a PR-ready diff report
* Agent can query: `search_products(query)` and `get_product(id)` safely.

### Phase 2: Dependency graph + “blast radius diff” (v1.2)

Acceptance criteria:

* `capability_graph.json` emitted
* diff shows: “new endpoint” plus “downstream edges changed”
* drift detects significant graph changes as a first-class drift type

### Phase 3: Remote serving + OAuth alignment (v2)

Acceptance criteria:

* Streamable HTTP MCP serve option
  DIY token schemes)
* TokenProvider adapters become real (your planned BFF) 

---

## 12) Risk register (high impact, with mitigations)

### Risk: SSRF / egress bypass

Mitigation:

* keep scheme allowlist, redirect hop validation, DNS resolution checks, private/metadata IP blocks (already in runtime contracts) 
  This aligns with OWASP SSRF prevention guidance.

### Risk: session leakage

Mitigation:

* never store secrets in artifacts
* redact before disk write (keep this invariant absolute)
* keep auth state out of toolpacks/bundles/evidence/baselines 
  Playwright storage state is sensitive and should be treated like credentials.

### Risk: scopes misclassification leads to dangerous tools

Miti-confidence high-risk forces review + blocks publish 

* ship conservative default templates (block admin/payment/write by default)

### Risk: provenance too often “unknown”

Mitigation:

* keep unknown budgk/site 
* improve signals slowly (initiator hints, repeated-run stability, hashed overlap) rather than “LLM magic”

### Risk: users bounce due to friction (Playwright, config, auth)

Mitigation:

* wow path must be offline and deterministe guided, with crisp errors and resume behavior
* keep flagship help minimal (you already do) 

---

## 13) Is it worth it, and will it impress users?

Yes, it’s worth pursuing **if you stay disciplined about the wedge**:

* diff-driven sed runtime
* scopes as reviewable boundaries
* verification as receipts

That combination is genuinely compelling and demonstrably useful today, and your docs already lock the right operat approve). 

Will it impress users?

* **The offline MCP demo will impress builders quickly.**
* **The ecommerce read-only pack will go viral if it works reliably on a bunch of sites and produces clean “search/product” tools without scary permissions.**
* The full “auth everywhere” dream will not be universal, but the guil seamless if you nail pause-resume and proof-of-auth.

[1]: https://github.com/alufers/mitmproxy2swagger?utm_source=chatgpt.com "GitHub - alufers/mitmproxy2swagger: Automagically reverse-engineer REST APIs via capturing traffic"
[2]: https://github.com/triggerdotdev/schema-infer?utm_source=chatgpt.com "GitHub - triggerdotdev/schema-infer: Infers JSON Schemas and Type Definitions from example JSON"
[3]: https://docs.devnetexperttraining.com/static-docs/OWASP-Cheat-Sheet-Series/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html?utm_source=chatgpt.com "Server Side Request Forgery Prevention - OWASP Cheat Sheet Series"
[4]: https://github.com/oasdiff/oasdiff?utm_source=chatgpt.com "GitHub - oasdiff/oasdiff: OpenAPI Diff and Breaking Changes"
[5]: https://owasp.org/www-community/attacks/Server_Side_Request_Forgery?utm_source=chatgpt.com "Server Side Request Forgery | OWASP Foundation"
[6]: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html?utm_source=chatgpt.com "Cross-Site Request Forgery Prevention - OWASP Cheat Sheet Series"
[7]: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html?utm_source=chatgpt.com "Server Side Request Forgery Prevention - OWASP Cheat Sheet Series"