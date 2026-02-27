You’re on the right track, but your docs are not “plug and play” yet because they contradict each other on **what the product is** and **what commands/features exist today**.

Below is what I’d fix, in priority order, plus exactly what to change in each doc.

---

## P0: Fix these before you try to get attention

### 1) One canonical user journey, one canonical CLI surface

Right now your docs tell two different stories:

* **Spec says** some capture and mint flags are *planned* (not implemented), like `--playbook` and `--verify-ui`.  
* **User guide shows** `--playbook` and `--verify-ui` as if users can run them now.  
* **README lists** `toolwright verify` as planned. 
* **But README also shows** mint output fields that imply UI verification exists (`evidence_summary`). 

**What to do (doc change, no code required yet):**

* Pick **one “Golden Path”** and make every doc follow it:

  * If `toolwright mint` is the product: make `mint` the wrapper that runs capture + compile + optional smoke verification.
  * Keep `capture`/`compile` as “advanced / low-level” commands in a separate section.
* Add a **Feature Status Matrix** in root README and user-guide:

  * **Shipped** vs **Planned** (and link to the roadmap issue for planned items).
* Any example script (like your “magic moment” CI script) must use the same Golden Path commands and flags, or it will destroy trust.

### 2) Stop claiming “mathematical proof” and stop over-promising compliance

Your positioning doc says enterprises “cannot mathematically prove correctness”. That is not a credible claim for UI verification. Replace with: **“produce auditable evidence that verification contracts passed”**.

Also, your EU AI Act timeline language is too absolute. The Act has staged applicability dates and a lot of confusion in the ecosystem. Use official timeline language and cite it. ([AI Act Service Desk][1])

**What to change:**

* Replace “EU AI Act turnkey compliance” with:

  * “Evidence and controls that help with audit readiness (logging, traceability, human oversight hooks).”
  * Add a disclaimer: “Not legal advice; confirm obligations with counsel.”

### 3) Remove the “Meta server lets agents request more power” vibe

Gemini’s criticism is correct on the security intuition: anything that looks like an agent can ask for more privilege is going to get you labeled “prompt injection highway.”

Your better direction is already in your replacement viewpoints: keep autonomy as **draft proposals only**, physically separated from the lockfile, and only merged by humans. 

Also, don’t justify “introspection” as listing tools. MCP already has standard discovery P docs emphasize security and consent patterns rather than agent self-governance. ([Model Context Protocol][2])

---

## P1: Your “Scopes” docs are currently underspecified (and this is your biggest wedge)

You’re right that your scopes description is not comprehensive enough. The current framing “infer scope from HTTP method and path” is not credible as-written. It’s a weak signal and the first thing a serious security reviewer will attack.

### What “Scopes” should mean in Toolwright (document this explicitly)

Write scopes as a **3-layer model**:

1. **Effect class (what kind of action is this)**

* `read`, `write`, `admin`, `external_side_effect`
* plus flags like `idempotent`, `creates_money_movement`, `credential_access`

2. **Resource domain (what it touches)**

* `users`, `billing`, `invoices`, `orders`, `auth`, `admin`, etc

3. **Sensitivity + blast radius**

* `pii`, `credentials`, `financial`, `compliance`, `prod_critical`
* risk tier: `low`, `med`, `high`, `critical`

Scopes should be derived as **candidate drafts**, not facts:

* Method + path is one heuristic.
* Payload fields and response shapes are another.
* Keyword/rule matches are another.
* Optional LLM classification can exist, but the output is **advisory** and must include a **reasoning trace** and confidence.

Your spec feedback already calls out the need for a `ScopeDraft` with a reasoning trace so humans trust it. 

### What to add to docs (concrete)

Add a dedicated `docs/scopes.md` (and link it from README + user guide) containing:

* **Scope object model**

  * `ScopeDraft`: suggested scopee pointers
  * `ToolEffect`: read/write/admin/external + mutation classification
  * `RiskSignals`: matched rules, payload keys, endpoint patterns

* **How inference actually works**

  * Step 1: deterministic heuristics (method/path/idempotency hints)
  * Step 2: rule engine (keywords in path/body/response)
  * Step 3: optional LLM labeling (advisory, never trusted)
  * Step 4: human approval merges draft into lockfile

* **Toolsets**

  * Explain toolsets as curated bundles of scopes/tools, and document the default behavior you already hint at (readonly default when toolsets exist and none selected). 

* **“Scope explain” output (docs-only for now if code not ready)**

  * Show an example of what the user sees:

    * “Why is this endpoint `billing:write:high_risk`?”
    * Show ruleat triggered it.

---

## P2: Tighten supply-chain and safety story (this is what makes it “boring and buyable”)

### 1) Lockfile needs a crisp contract

Your docs mention semantic hashing and drift gating. Keep it, but define it like a real artifact:

* What exactly is hashed (schema, scopes, effect class, redaction profile, toolset membership)
* What invalidates it (schema drift, new endpoint, changed auth surface)
* What fails where (CI fails at build time, runtime denies tool call)

This is aligned with your “deterministic artifacts and rollbacks” narrative. 

### 2) Evidence and retention must be treated as a liability

Your viewpoints already recommend redaction profiles + TTL because storing captures can become a compliance problem. 

Document:

* Redaction profiles (PII, tokens, secrets)
* TTL on evidence bundles
* “Export sanitized bundle” vs “raw capture never leaves machine”
* Threat model and SSRF stance

 best practices to show you’re not inventing this in a vacuum. ([Model Context Protocol][3])

### 3) Rename “Meta server” to “Control Plane API” everywhere

This is a real branding and trust improvement, and your viewpoints already call it out. 

---

## File-by-file update plan

### Root README.md (project)

**Must add**

* 10-line “What is Toolwright” with the Golden Path
* Feature status matrix (Shipped vs Planned)
* “Security model in 6 bullets” (lockfile, least privilege, approvals, redaction, deny-by-default, evidence)unts with “thousands” and cite a stable source if you keep numbers (PulseMCP is fine but it changes daily). ([PulseMCP][4])

**Must remove/soften**

* “Mathematical proof”
* Over-confident EU AI Act deadline wording (replace with cited, scoped statement). ([AI Act Service Desk][1])

### examples/README.md

**Goal:** copy-paste success in under 5 minutes.

* One command sequence
* Expected output pasted
* Troubleshooting for missing Playwright browsers
* Explicit: “This is the supported happy path. Advanced capture/compile is below.”

### user-guide.md

**Restructure**

* Start with Golden Path: mint → approve → serve/run → drift gate
* Put capture/compile/enforce under “Advanced”
* Add a full “Scopes” chapter (link to `docs/scopes.md`)

**Fix inconsistencies**

* Don’t document flags as supported if spec says planned.  

### SPEC.md

**Update**

* Replace “Meta server” language with “Control Plane API”
* Formalize `ScopeDraft` and reasoning trace
* Formalize “Draft Expansion Bundle” that is separate from the lockfile. 
* Add “VerificationContract” selectors that look like Testing Library (ByRole/ByLabelText) rather than brittle DOM matching

### STRATEGY.md

**Update positioning with sal registry announcement and repo. ([Model Context Protocol Blog][5])

* If you mention Runlayer funding, cite it. ([Runlayer][6])
* Make competitors a spectrum: gateways, reg, and explain “we are build-time supply chain + verification”.

### RELEASE_PLAN.md

* Convert it into a “Definition of Done” checklist for:

  * “Plug-and-play on a clean machine”
  * “Magic moment CI passes”
  * “Docs match shipped behavior”
  * “No legacy names remain”
* Anything already done should be marked as such or moved to a changelog.

### magic_moment_ci.sh

* Make it the canonical automation of the Golden Path.
* It should fail with one-line actionable errors and match what README promises.

---

## Are you on the right track?

Yes, if you commit to this framing:

* **Build-time governance**, not “agents governing themselves”
* **Draft proposals**, not dynamic permission escalation
* **Verification contracts + evidence**, not “we prove correctness”
* **Scopes as risk and effect modeling**, not “HTTP method mapping”

[1]: https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act?utm_source=chatgpt.com "Timeline for the Implementation of the EU AI Act"
[2]: https://modelcontextprotocol.io/specification/2025-03-26/server/tools?utm_source=chatgpt.com "Tools"
[3]: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices?utm_source=chatgpt.com "Security Best Practices"
[4]: https://www.pulsemcp.com/servers?utm_source=chatgpt.com "MCP Server Directory: 8250+ updated daily"
[5]: https://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/?utm_source=chatgpt.com "Introducing the MCP Registry | Model Context Protocol Blog"
[6]: https://www.runlayer.com/blog/runlayer-raises-11m-to-scale-enterprise-mcp-infrastructure?utm_source=chatgpt.com "Runlayer Raises $11M to Scale Enterprise MCP ..."

---

You’re close, but the docs are **not fully consistent yet**. The **direction in `SPEC_VIEWPOINTS.md` (Feb 2026) is the right shape** for a v1, but older/adjacent docs still leak the “agents govern themselves” vibe and a few “shipped vs planned” mismatches.

## 1) Consistency check: what’s currently contradictory

### A) “Meta server for agents” conflicts with your locked non-goals

* vNext spec says **no agent-led approvals** and **no in-protocol approve tools exposed to agents**. 
* But `user-guide.md` explicitly says `toolwright mcp meta` exposes governance tools “as an MCP server for agents.” 
* Root README lists `toolwright mcp meta` as a first-class command. 

**Fix:** Either (1) remove `mcp meta` from the public surface for now, or (2) keep it but hard-frame it as **operator/CI tooling only**, never agent-callable, matching your revised “Control Plane API” rules. 

### B) “Planned vs implemented” is muddled (even inside the same doc)

`SPEC.md` marks `--verify-ui` and `--playbook` as planned/not implemented, but then also claims it writes `evidence_summary.json` “when --verify-ui is used.” That’s internally inconsistent. 

**Fix:** Add a single “Status: shipped/planned” legend and enforce it everywhere. If `--verify-ui` is not real today, remove any output claims tied to it.

### C) Command naming is drifting between docs

* vNext spec uses `toolwright diff` as a core outcome. 
* README advertises `toolwright plan` as the deterministic diff report. 

**Fix:** Pick one. I’d keep `diff` as canonical (it’s industry-standard) and make `plan` an alias, because Terraform brain expects “plan” but security/gov tools expect “diff”.

### D) Strategy doc has a concrete “wrong command” bug

`STRATEGY.md` says the “Compiler Target: MCP Adapter” but the example command uses `--format openapi` (that reads like a doc bug, or a confused flag definition). 

**Fix:** Update that example to the actual MCP target you intend to ship.

### E) User guide contains an in-doc TODO that contradicts “release-ready” posture

The user guide literally says the `approve` command set is “really confusing” and calls out `approve reject` as “insanely confusing.” 

**Fix:** Move that into an internal TODO doc or GitHub issue, not the user guide.

---

## 2) Is this what the project should be like?

Yes, **if you treat `SPEC_VIEWPOINTS.md` as the canonical product definition**: Toolwright is a **deterministic build system for agent capabilities** producing toolpacks + lockfiles + verification contracts + drift gates, and it **feeds runtime layers** instead of competing as one.  

The biggest “correct” call in that rewrite is de-scoping “Full Meta” and agent-driven expansion. You explicitly lock:

* no agent privilege negotiation,
* no agent-led approvals,
* no “proof of correctness” claims. 

That framing is the difference between “security theater tool” and “real governance artifact pipeline.”

---

## 3) Is it worth pursuing?

**Yes, if you commit to the build-system wedge and ship a tight v1.** The MCP ecosystem is clearly heating up:

* There’s an official MCP Registry preview (with warnings about breaking changes before GA). ([Model Context Protocol Blog][1])
* MCP is being positioned as a cross-client integration layer (OpenAI documents “connectors” as OpenAI-maintained MCP wrappers, and remote MCP servers as any server implementing MCP). ([OpenAI Platform][2])
* MCP security guidance and authorization-related best practices are now explicitly documented. ([Model Context Protocol][3])
* Packaging is standardizing too: MCP Bundle format `.mcpb` is being promoted for portable local servers. ([Model Context Protocol Blog][4])
* There are already adjacent players: MCPTrust is a runtime security proxy with lockfile, drift, signing, policy checks, etc. ([GitHub][5])
* And money is moving: Runlayer publicly says it raised a seed round to scale “enterprise MCP infrastructure.” ([Runlayer][6])

### The real risk

You can easily get squeezed if you look like “yet another runtime gateway / proxy.” MCPTrust and others are already there. ([GitHub][5])
Your v1 must scream: **“I generate the governable artifact set from reality (capture), and I make drift/verify gateable in CI.”** That is meaningfully different.

### Another risk: compliance positioning

Your own `OPENAI_VIEWPOINTS.md` is right: EU AI Act language is time-sensitive and easy to overstate. 
The EU is still clarifying timing and guidance in public. ([Reuters][7])
So do not sell “turnkey compliance.” Sell “audit-ready evidence and controls.”

---

## 4) Are you on the right track?

**Yes, technically and strategically, with one condition:** you must clean the docs so they present **one coherent v1**.

### Do this doc cleanup pass (fast, high leverage)

1. **Make `SPEC_VIEWPOINTS.md` the only “SPEC”**. Move `SPEC.md` to `docdd a banner at the top that it’s historical. (Right now it actively conflicts with the rewrite.) 
2. Replace “meta server” phrasing everywhere with “Control Plane API” and explicitly state “operator/CI only” (matching the spec). 
3. Add a **single status matrix** in the README: `shipped`, `alpha`, `planned`, and enforce it for every command and flag (especially `--verify-ui`, `--playbook`, `compliance report`). 
4. Pick **diff vs plan** naming and align across all docs.  
5. Remove the in-guide TODO about `approve` command naming and fi
6. Update `STRATEGY.md` command examples so they are mechanically correct. 
7. A clearly explain why you are not). This is now a visible standard in the ecosystem. ([Model Context Protocol Blog][4])

### My practical recommendation

Keep building. But **do not** ship a public story tr more power” or “approve” things. That is the quickest way tot

* [theverge.com](https://www.theverge.com/news/867673/claude-mcp-app-interactive-slack-figma-canva?utm_source=chatgpt.com)
* [Reuters](https://www.reuters.com/business/media-telecom/code-practice-help-companies-with-ai-rules-may-come-end-2025-eu-says-2025-07-03/?utm_source=chatgpt.com)
* [Reuters](https://www.reuters.com/world/europe/artificial-intelligence-rules-go-ahead-no-pause-eu-commission-says-2025-07-04/?utm_source=chatgpt.com)
* [apnews.com](https://apnews.com/article/155157e2be2e42d0f1acca33983d8c82?utm_source=chatgpt.com)


[1]: https://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/ "Introducing the MCP Registry | Model Context Protocol Blog"
[2]: https://platform.openai.com/docs/guides/tools-connectors-mcp "Connectors and MCP servers | OpenAI API"
[3]: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices "Security Best Practices - Model Context Protocol"
[4]: https://blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb/ "Adopting the MCP Bundle format (.mcpb) for portable local servers | Model Context Protocol Blog"
[5]: https://github.com/mcptrust/mcptrust "GitHub - mcptrust/mcptrust: Runtime security proxy for MCP: lockfile enforcement, drift detection, artifact pinning, Sigstore/Ed25519 signing, CEL policy, OpenTelemetry tracing. Works with Claude Desktop, LangChain, AutoGen, CrewAI."
[6]: https://www.runlayer.com/blog/runlayer-raises-11m-to-scale-enterprise-mcp-infrastructure "Runlayer Raises $11M to Scale Enterprise MCP Infrastructure"
[7]: https://www.reuters.com/business/media-telecom/code-practice-help-companies-with-ai-rules-may-come-end-2025-eu-says-2025-07-03/ "Code of practice to help firms comply with AI rules may apply end 2025, EU says | Reuters"

---

Yes, you’re on the right track, but only if you **lean hard into the “build system for governable tools”** and stop drifting toward “runtime proxy / firewall” positioning.

### Where differentiation is real (and good)

Your strongest wedge is:

**Capture or import reality → compile a portable toolpack → produce reviewable artifacts (lockfile, policy, evidence) → drift gate in CI → then hand off to whatever runtime.**

That’s meaningfully different from the big emerging cluster that is trying to be **the runtime security layer** for MCP. MCPTrust explicitly frames itself as a lockfile + firewall and enforces deny-by-default at runtime. ([mcptrust.dev][1]) Runlayer is going after enterprise MCP infrastructure and “control how AI interacts with tools and data.” ([runlayer.com][2])

If you compete there, you get squeezed.

### Where you’re *not* differentiated (danger zone)

If Toolwright is described as:

* “a proxy that blocks unsafe tool calls”
* “a firewall for MCP”
* “runtime enforcement for agents”

…then you look like MCPTrust / Runlayer / other agent security vendors. ([mcptrust.dev][1])

### The 2 decisions that determine whether you win the wedge

1. **Be the artifact generator, not the runtime.**
   Ship outputs that are obviously useful even if the user runs a different runtime or client. That’s durable.

2. **Standardize around ecosystem packaging and safety expectations.**
   MCP is standardizing distribution with `.mcpb`. If you output toolpacks that can become `.mcpb` cleanly (or explain why not), you fit the ecosystem rather than fighting it. ([Model Context Protocol Blog][3])

### Practical “differentiation test”

If a skeptical buyer asks “why not just use MCPTrust,” your best answer has to be:

* “MCPTrust secures what you already have at runtime. We generate the thing you can safely run in the first place, from real captures/imports, with reviewable diffs, evidence, and CI gates.”

If you can’t say that cleanly, you’re not differentiated.

### Recommendation

Double down on:

* deterministic capture/import → compile
* **diff/plan that is review-grade**
* drift gates in CI
* evidence summaries that explain “what changed, why it matters”
* clean path to `.mcpb` packaging

De-emphasize:

* “meta server for agents”
* any story that implies agents request privileges or approve anything

Confidence: **0.8**. The ecosystem signals (registry, bundling, security vendors) strongly suggest the market is bifurcating into “distribution/build” vs “runtime control.” ([Model Context Protocol Blog][4])

[1]: https://mcptrust.dev/?utm_source=chatgpt.com "MCPTrust — Lockfile for MCP servers"
[2]: https://www.runlayer.com/blog/runlayer-raises-11m-to-scale-enterprise-mcp-infrastructure?utm_source=chatgpt.com "Runlayer Raises $11M to Scale Enterprise MCP ..."
[3]: https://blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb/?utm_source=chatgpt.com "Adopting the MCP Bundle format (.mcpb) for portable local ..."
[4]: https://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/?utm_source=chatgpt.com "Introducing the MCP Registry | Model Context Protocol Blog"

---

Yes. You have too many commands and too much surface area for a new tool. People will bounce unless you give them one obvious “do the thing” path.

The right move is exactly what you said: **one flagship workflow**, everything else becomes either hidden plumbing or “advanced”.

## What to do
### 1) Collapse to one flagship command
Make this the only thing most people learn:

**`toolwright build`**  
Input: capture/import + config  
Output: a shippable bundle + review artifacts

It should do, in one run:
- compile toolpack
- generate policy defaults
- generate lockfile snapshot
- generate diff report (if prior exists)
- generate evidence summary
- optionally run verification gates (lightweight)

Everything else should be either:
- subcommands under `build`, or
- “advanced” and not mentioned in the first 80% of docs.

### 2) Keep the rest, but reframe as phases, not separate products
If you keep commands, they should map to a simple pipeline mental model:

- `toolwright import` (or `capture`)  
- `toolwright build` (flagship)  
- `toolwright verify` (optional)  
- `toolwright drift` (CI mode)  
- `toolwright serve` (optional runtime integration)

Everything else should be internal or power-user.

### 3) Remove or hide anything that smells like governance bureaucracy
Anything like:
- `approve reject`
- multiple approval verbs
- “meta server”

…is adoption poison early. Keep the workflow, but make it feel like Git:
- `toolwright approve` should basically mean “update lockfile from current build output and sign it”
- “reject” is just “don’t merge the PR”

Your own user guide calling approve confusing is a red flag. Fix it by simplifying, not documenting the confusion.

## Rule of thumb
If a new user can’t succeed with **two commands** on day one, you lose.

Example “magic moment” should be:
1) `toolwright init` (optional, creates config)
2) `toolwright build` (produces bundle + report)

## Tradeoff
- Fewer commands means less explicit control and some power users will complain.
- But adoption beats purity. You can re-expand later once you have users.

Recommendation: **Yes, consolidate now.** Your current docs read like a control plane, not a tool people try on a whim.