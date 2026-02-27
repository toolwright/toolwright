# Toolwright — Project Specification v1.0

> **Self-expanding, self-repairing, human-correctable tool infrastructure for AI agents.**

*A "wright" is a maker — playwright, wheelwright, shipwright. Toolwright is the system that builds, repairs, governs, and evolves tools for AI agents at runtime.*

**Language:** Python 3.11+
**Foundation:** CaskMCP (86 commits, published on PyPI, 32K lines source, 25K lines tests)
**License:** MIT

---

## Table of Contents

1. [Vision & Positioning](#1-vision--positioning)
2. [Architecture Overview](#2-architecture-overview)
3. [Feature Map: CaskMCP → Toolwright](#3-feature-map-caskmcp--toolwright)
4. [The Five Pillars](#4-the-five-pillars)
   - 4.1 [CONNECT — Self-Expanding Toolkit](#41-connect--self-expanding-toolkit)
   - 4.2 [GOVERN — Safety & Trust Layer](#42-govern--safety--trust-layer)
   - 4.3 [HEAL — Self-Repairing Tools](#43-heal--self-repairing-tools)
   - 4.4 [KILL — Circuit Breakers & Tool Termination](#44-kill--circuit-breakers--tool-termination)
   - 4.5 [CORRECT — Human-in-the-Loop Behavioral Rules](#45-correct--human-in-the-loop-behavioral-rules)
5. [Tech Stack & Dependencies](#5-tech-stack--dependencies)
6. [Migration Strategy: CaskMCP → Toolwright](#6-migration-strategy-caskmcp--toolwright)
7. [Implementation Plan](#7-implementation-plan)
8. [Open-Source Library Evaluation](#8-open-source-library-evaluation)

---

## 1. Vision & Positioning

### The Problem

Agents today are trapped in a static toolkit. If a tool breaks, the agent fails. If the agent needs a capability it doesn't have, the human has to manually find, install, configure, and authenticate a new tool. When the agent uses a tool incorrectly, there's no way to correct the behavior without retraining the model or rewriting prompts.

**For agent builders:**

1. **Static toolkits.** An agent ships with N tools. If a user needs tool N+1, the developer has to build and deploy it. There's no runtime extensibility.

2. **Fragile integrations.** APIs change, auth tokens expire, rate limits shift, schemas evolve. When a tool breaks, the agent retries, fails, and the user sees an error. Nobody diagnoses or fixes the break automatically.

3. **No behavioral correction.** When an agent misuses a tool — calling `delete_task` without confirmation, fetching all records without pagination, using the wrong endpoint for the job — the only fixes are prompt engineering or code changes. There's no way for a user to say "don't do that again" and have it stick.

4. **Unsafe expansion.** Even if an agent *could* add tools, there's no safety layer. An agent that can install arbitrary tools is an agent that can exfiltrate data, delete resources, or rack up API bills.

5. **Tool sprawl.** Anthropic's own research shows 134K tokens consumed by tool definitions before agents start working. Even with Tool Search, Claude picks the wrong tool 12-26% of the time. Agents need dynamically scoped, minimal toolsets — not everything-all-at-once.

**For the ecosystem:**

- **Composio, Zapier MCP:** Pre-built catalogs. If your API isn't listed, you're stuck. When something breaks, you file a ticket.
- **FastMCP, Speakeasy:** Generate MCP servers from OpenAPI specs, but as a manual developer command, not agent-invokable at runtime.
- **MCPTrust, mcp-scan:** Govern existing tools, but don't create new ones or repair broken ones.
- **LangSmith, Braintrust, AgentOps:** Observe what agents do. Don't correct, repair, or expand.
- **Nobody** has a system where the agent says "I need this capability" and gets it, safely, within the flow of work.

### The Solution

Toolwright changes this. It is an MCP meta-server that gives agents the power to:

- **Connect** to new APIs mid-conversation by compiling OpenAPI specs into governed MCP tools
- **Heal** broken tools by diagnosing failures and recompiling tool definitions at runtime
- **Correct** tool usage through durable human-in-the-loop behavioral rules that persist across sessions
- **Govern** every tool with risk classification, cryptographic signing, and human approval gates
- **Kill** misbehaving tools instantly with circuit breakers and in-flight cancellation

The governance layer is what makes self-expansion *safe* instead of terrifying. Every new capability is risk-classified, signed, approved, and auditable. Toolwright doesn't remove humans from the loop — it puts them in the right part of the loop.

### Unique Value

Toolwright is the only system that closes the full loop: "tool doesn't exist" → "tool exists and works" → "tool broke" → "tool is fixed" → "agent used it wrong" → "agent won't do that again." Nobody else has this.

### Why Python

The original Toolwright spec assumed TypeScript. That was wrong. CaskMCP — the production foundation — is **99.2% Python** with:

- Published on PyPI (`pip install caskmcp`)
- 86 commits of production code
- 32,641 lines of source code
- 24,944 lines of tests
- CI/CD with GitHub Actions passing
- Comprehensive documentation

**Python is also the right choice for users:**

| Factor | Python | TypeScript |
|---|---|---|
| AI/ML ecosystem fit | Primary language for LangChain, CrewAI, Anthropic Agent SDK, OpenAI SDK | Secondary |
| MCP SDK maturity | v1.26.0 stable, v2 in development (Anthropic-maintained) | v1.x stable |
| Installation friction | `pip install toolwright` — no Node.js required | Requires Node.js runtime |
| OpenAPI tooling | Pydantic, httpx, PyYAML — all already in use | swagger-parser, axios |
| Cryptography | `cryptography` library with Ed25519 — already in use | node:crypto |
| User base | Agent builders overwhelmingly work in Python | Frontend/full-stack devs |

Switching to TypeScript would destroy weeks of production work for zero user benefit.

---

## 2. Architecture Overview

### Directory Structure (Current → Renamed)

```
toolwright/                       # was: caskmcp/
├── __init__.py
├── __main__.py
├── branding.py
├── cli/                          # 25+ commands, Click-based
│   ├── main.py                   # Entry point: `toolwright` or `tw`
│   ├── mint.py                   # One-command capture + compile
│   ├── approve.py                # Lockfile approval workflows
│   ├── enforce.py                # Standalone enforcement gateway
│   ├── repair.py                 # Self-repair CLI
│   ├── propose.py                # Agent proposal workflows
│   └── ...
├── core/                         # Domain logic (no CLI, no IO)
│   ├── approval/                 # Ed25519 signing, lockfile management
│   ├── audit/                    # Structured traces, decision logging
│   ├── auth/                     # Auth detection, profiles
│   ├── capture/                  # HAR, OTEL, OpenAPI, Playwright, WebMCP
│   ├── compile/                  # Tool manifest, policy, contract, baseline
│   ├── compliance/               # EU AI Act reporting
│   ├── correct/                  # NEW: Behavioral rule engine
│   ├── drift/                    # Schema drift detection
│   ├── enforce/                  # Decision engine, policy engine, confirmation
│   ├── enrich/                   # Optional LLM enrichment
│   ├── health/                   # NEW: Proactive health checker
│   ├── init/                     # Project initialization
│   ├── kill/                     # NEW: Circuit breaker state machine
│   ├── normalize/                # Path normalization, aggregation, tagging
│   ├── plan/                     # Diff/change planning
│   ├── proposal/                 # Agent draft proposals
│   ├── repair/                   # Diagnosis + patch engine
│   ├── runtime/                  # Container runtime emission
│   ├── scope/                    # Scope filtering
│   ├── verify/                   # Replay, contracts, outcomes, provenance
│   └── toolpack.py               # Toolpack resolution
├── mcp/                          # MCP server implementations
│   ├── server.py                 # Governed MCP server (930 lines)
│   ├── meta_server.py            # Read-only introspection server (635 lines)
│   └── _compat.py                # MCP SDK compatibility layer
├── models/                       # Pydantic data models
│   ├── capture.py                # HttpExchange, CaptureSession
│   ├── decision.py               # DecisionRequest/Result, ReasonCode
│   ├── drift.py                  # DriftItem, DriftReport
│   ├── endpoint.py               # Endpoint, Parameter, AuthType
│   ├── flow.py                   # FlowEdge, FlowGraph
│   ├── policy.py                 # Policy, PolicyRule, RuleType
│   ├── proposal.py               # DraftProposal, MissingCapability
│   ├── repair.py                 # DiagnosisItem, PatchItem
│   ├── rule.py                   # NEW: BehavioralRule models
│   ├── scope.py                  # Scope, ScopeFilter
│   └── verify.py                 # VerifyReport, EvidenceBundle
├── storage/                      # Filesystem storage
├── ui/                           # Rich TUI (81K total)
│   ├── console.py
│   ├── prompts.py
│   ├── echo.py
│   └── flows/                    # Wizard flows (repair, init, gate_review, config)
└── utils/                        # Canonical digests, naming, schema versioning
```

### Request Flow

```
Agent ──► MCP Server ──► Decision Engine ──► Rule Engine ──► Circuit Breaker
              │               │                  │                │
              │          Lockfile?            Behavioral      Per-tool
              │          Policy?              rules pass?     health OK?
              │          Approved?                │                │
              │               │                  │                │
              ▼               ▼                  ▼                ▼
         Proxy Layer ◄── ALLOW/DENY ◄── ALLOW/DENY ◄── ALLOW/DENY
              │
              ▼
         Upstream API ──► Response ──► Audit Log
```

**Key architectural principle:** The existing MCP server (`server.py`, 930 lines) already has a complete proxy layer with request construction, auth injection, SSRF protection, redirect validation, and content-type filtering. The CORRECT and KILL pillars intercept calls **before** this existing proxy, not replace it.

---

## 3. Feature Map: CaskMCP (/Users/thomasallicino/oss/cask) → Toolwright

### What Exists (by Pillar)

| Pillar | Completion | What's Built | What's Missing |
|---|---|---|---|
| **CONNECT** | 92% | OpenAPI/HAR/OTEL/browser/WebMCP capture, risk classification, auth extraction, tool emission, MCP server, client config gen | OAuth 2.0 upstream auth, URL elicitation flow |
| **GOVERN** | 96% | Lockfile + Ed25519 signing, policy evaluation, drift detection, audit trail, evidence bundles, compliance reporting | Hash-chained audit log (optional hardening) |
| **HEAL** | 72% | `repair` with SAFE/APPROVAL_REQUIRED/MANUAL classification, diagnosis from audit+drift+verify, proposal system | Proactive health checker, failure classifier, meta-tool exposure |
| **KILL** | 76% | Fail-closed enforcement, rate limiting, SSRF protection, confirmation flow, dry-run mode | Circuit breaker state machine, response size limits, meta-tool exposure |
| **CORRECT** | 12% | Compile-time policy rules (allow/deny/confirm/budget/audit/redact) | Durable behavioral rule engine, runtime CRUD, session tracking, violation feedback |

### Lines of Code (Existing)

| Module | Lines | Role |
|---|---|---|
| `cli/` | ~6,200 | CLI commands (Click) |
| `core/approval/` | ~1,600 | Ed25519 signing, lockfile |
| `core/audit/` | ~500 | Structured trace logging |
| `core/auth/` | ~600 | Auth detection, profiles |
| `core/capture/` | ~2,600 | All five capture sources |
| `core/compile/` | ~2,100 | Tool manifest, policy, contracts |
| `core/drift/` | ~850 | Schema drift detection |
| `core/enforce/` | ~1,600 | Decision engine, policy engine, confirmation |
| `core/normalize/` | ~1,500 | Path normalization, aggregation |
| `core/plan/` | ~620 | Change planning |
| `core/proposal/` | ~1,300 | Agent draft proposals |
| `core/repair/` | ~860 | Diagnosis + patch engine |
| `core/scope/` | ~700 | Scope filtering |
| `core/verify/` | ~1,200 | Replay, contracts, outcomes, provenance |
| `mcp/` | ~1,700 | MCP server + meta server |
| `models/` | ~2,400 | Pydantic data models |
| `storage/` | ~400 | Filesystem storage |
| `ui/` | ~2,800 | Rich TUI + wizard flows |
| `utils/` | ~1,000 | Canonical digests, naming |
| **Total source** | **~32,600** | |
| **Total tests** | **~24,900** | |

### Net New Code Required

| Component | Est. Lines | Priority |
|---|---|---|
| Behavioral rule engine (`core/correct/`) | ~650 | P0 |
| Rule models (`models/rule.py`) | ~200 | P0 |
| Circuit breaker (`core/kill/`) | ~250 | P1 |
| Meta-tool handlers (correct + kill + heal) | ~500 | P1 |
| Proactive health checker (`core/health/`) | ~200 | P2 |
| OAuth 2.0 upstream auth | ~300 | P2 |
| CLI commands (rules, kill, health) | ~400 | P1 |
| Hash-chained audit log (upgrade) | ~150 | P3 |
| Tests for all new code | ~1,800 | P0-P2 |
| **Total net new** | **~4,450** | |

**That's ~4,450 lines of net new code against a 57,500-line codebase.** CaskMCP is ~88% of Toolwright by functionality.

---

## 4. The Five Pillars

### 4.1 CONNECT — Self-Expanding Toolkit

The agent can discover, compile, authenticate, and register new tools at runtime. No manual installation. No pre-built catalogs. Point it at an API, and it builds its own tools.

**Status: 92% complete. Minimal new work.**

#### What Exists

The entire capture-compile-serve pipeline is production-ready:

**Capture sources (5/5):**
- `HARParser` — Parse HTTP Archive files into `CaptureSession` objects
- `OTELParser` — Parse OpenTelemetry trace exports
- `OpenAPIParser` — Bootstrap tools from OpenAPI 3.0/3.1 specs
- `PlaywrightCapture` — Record browser traffic (interactive, headless, scripted)
- `WebMCPCapture` — Discover tools via W3C WebMCP, MCP-B polyfill, HTML meta tags, `.well-known/mcp-tools.json`

**Normalization pipeline:**
- `PathNormalizer` — Collapse path parameters into `{param}` placeholders
- `EndpointAggregator` — Merge exchanges into `Endpoint` models with inferred schemas
- `FlowDetector` — Detect data dependencies between endpoints (`FlowGraph`)
- `Tagger` — Domain tagging (auth, commerce, admin, etc.)

**Compilation:**
- `ToolManifestGenerator` — Agent-consumable tool manifests with JSON Schema, risk tiers, flow metadata
- `PolicyGenerator` — Default enforcement policies (allow/deny/confirm/budget/audit/redact)
- `ContractCompiler` — OpenAPI 3.1 contract spec
- `BaselineGenerator` — Snapshot for drift detection
- `ToolsetGenerator` — Named toolsets (readonly, readwrite, all)

**MCP Server:**
- `CaskMCPMCPServer` (930 lines) — Full MCP stdio server with:
  - Dynamic tool registry from compiled manifests
  - Universal dispatcher routing tool calls to upstream APIs
  - Request construction (path params, query params, body, headers)
  - Auth injection (Bearer token, API key, cookie)
  - SSRF protection, redirect validation, content-type filtering
  - Next.js build ID auto-resolution
  - `tools/list_changed` notifications
  - Audit logging of every decision

**Client config generation:**
- Claude Desktop JSON snippets
- Codex format
- Auto-derived server names from toolpack origin

#### What's Missing

**OAuth 2.0 for upstream API auth (P2, ~300 lines):**

The current auth model is env-var / header injection: you pass `--auth "Bearer xyz"` and Toolwright injects it. This works for API keys and static tokens but not for OAuth-protected APIs that need token refresh.

**Implementation approach — use `authlib`:**

```python
# toolwright/core/auth/oauth.py
from authlib.integrations.httpx_client import AsyncOAuth2Client

class OAuthCredentialProvider:
    """Manage OAuth 2.0 tokens for upstream API access."""

    def __init__(self, client_id: str, client_secret: str, token_endpoint: str):
        self.client = AsyncOAuth2Client(
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint=token_endpoint,
        )
        self._token: dict | None = None

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._token is None or self._is_expired():
            self._token = await self.client.fetch_token(
                self.client.token_endpoint,
                grant_type="client_credentials",
            )
        return self._token["access_token"]
```

**Why `authlib` over building from scratch:**
- Battle-tested OAuth 2.0/2.1 library (4.7K GitHub stars, actively maintained)
- Native httpx integration (we already use httpx)
- Supports client_credentials, authorization_code with PKCE, token refresh
- Zero configuration overhead — drop-in replacement for static auth headers
- MIT licensed

**OAuth is an optional dependency** — added to `[oauth]` extras, not core. Most users will continue using API keys and Bearer tokens.

**MCP spec OAuth alignment (P3, deferred):**

The MCP specification (2025-11-25) defines comprehensive OAuth 2.0 authorization for MCP servers acting as Resource Servers. This is about **clients authenticating to Toolwright's MCP server**, not Toolwright authenticating to upstream APIs. This is a separate concern and should be deferred until remote MCP transport (Streamable HTTP) is prioritized. For stdio transport (current), OAuth is not applicable per the MCP spec.

---

### 4.2 GOVERN — Safety & Trust Layer

Governance is not a feature. It is the foundation that makes everything else safe. Every tool Toolwright creates comes out governed: risk-classified, Ed25519 signed, human-approved, and audited.

**Status: 96% complete. Polish only.**

#### What Exists

This is Toolwright's most mature pillar. Everything below is already built, tested, and shipped:

**Lockfile-based approval (`core/approval/`):**
- `LockfileManager` — Track tool approval statuses (pending, approved, rejected)
- `ApprovalSigner` — Ed25519 signing with auto-generated keypairs
- Key rotation and revocation with trust store
- Artifact integrity verification via SHA-256 digests
- Approver allowlist via `TOOLWRIGHT_APPROVERS` env var
- Snapshot materialization for baseline pinning

**Policy evaluation (`core/enforce/engine.py`):**
- `PolicyEngine` — Priority-ordered rule evaluation
- Rule types: allow, deny, confirm, budget, audit, redact
- `MatchCondition` — Host/path/method/risk-tier/scope matching with regex support
- `BudgetTracker` — Per-minute and per-hour sliding-window rate limiting
- State-changing operation overrides

**Decision engine (`core/enforce/decision_engine.py`):**
- `DecisionEngine` — Unified decision logic for gateway and MCP runtime
- Integrity verification (lockfile digest vs runtime artifacts)
- Approval status checking with signature validation
- Policy evaluation cascade
- Confirmation flow integration
- Network safety enforcement

**Drift detection (`core/drift/engine.py`):**
- `DriftEngine` — Compare endpoint sets or baselines
- Drift types: BREAKING, AUTH, RISK, ADDITIVE, SCHEMA, PARAMETER
- Severity levels: CRITICAL, ERROR, WARNING, INFO
- Flow-aware broken dependency detection

**Audit logging (`core/audit/`):**
- `AuditLogger` with FileAuditBackend (JSONL) and MemoryAuditBackend
- `DecisionTraceEmitter` — Structured decision traces
- Event types: capture, compile, drift, enforce, confirmation, budget, block

**Verification (`core/verify/`):**
- Contract schema validation
- Deterministic replay verification
- Outcomes checking with playbooks
- Provenance scoring with configurable thresholds

**Evidence bundles:**
- SHA-256 digests for all artifacts
- Structured reports in JSON and Markdown

**Compliance (`core/compliance/`):**
- EU AI Act compliance reporting (human oversight, tool inventory, risk management)

#### What's Missing (Optional Hardening)

**Hash-chained audit log (P3, ~150 lines):**

Current audit logging writes structured JSONL entries. Each entry is self-contained but not cryptographically chained. Hash-chaining adds tamper evidence:

```python
# Each entry includes prev_hash, creating an append-only chain
class ChainedAuditEntry(BaseModel):
    sequence: int
    prev_hash: str  # SHA-256 of previous entry
    event: AuditEvent
    timestamp: str
    entry_hash: str  # SHA-256 of (sequence + prev_hash + event + timestamp)
```

This is a nice-to-have hardening measure. The current audit system is already functional and the existing Ed25519 signing on approvals provides the primary integrity guarantee. Hash-chaining adds defense-in-depth for the audit trail itself.

---

### 4.3 HEAL — Self-Repairing Tools

When a tool call fails, the agent doesn't just retry and give up. It diagnoses *why* the tool broke and fixes it — refreshing credentials, recompiling schemas, rolling back to known-good definitions.

**Status: 72% complete. Moderate new work.**

#### What Exists

**Repair engine (`core/repair/engine.py`, 857 lines):**
- `RepairEngine` — Diagnoses issues from three evidence sources:
  - Audit logs (DENY entries → denied capabilities)
  - Drift reports (schema changes → broken tools)
  - Verify reports (failed contracts → integrity issues)
- Three-tier safety classification:
  - **SAFE** — read-only diagnostics (auto-runnable)
  - **APPROVAL_REQUIRED** — grants new capability (needs human review)
  - **MANUAL** — requires investigation or re-capture
- Patch actions: `gate_allow`, `gate_sync`, `gate_reseal`, `verify_contracts`, `verify_provenance`, `investigate`, `re_mint`, `review_policy`, `add_host`
- Deterministic diagnosis IDs (SHA-256 of key fields)
- Cluster-based grouping for related issues
- Redaction of sensitive data in evidence

**Repair CLI (`cli/repair.py`):**
- `cask repair --toolpack <path> [--from <context>...] [-o <dir>]`
- Outputs: `repair.json`, `repair.md`, `diagnosis.json`, `patch.commands.sh`
- Auto-discovery of context files in toolpack

**Repair TUI (`ui/flows/repair.py`):**
- Interactive repair wizard with risk-colored tables
- Guided patch selection

**Proposal system (`core/proposal/`):**
- `ProposalEngine` — Agent draft proposals for new capabilities
- `ProposalCompiler` — Generate endpoint catalogs from captures
- `ProposalPublisher` — Publish accepted proposals with confidence/risk filtering
- CLI: `propose create`, `propose list`, `propose show`, `propose approve`, `propose reject`, `propose publish`

#### What's Missing

**Proactive health checker (P2, ~200 lines):**

`core/health/checker.py`:

```python
class HealthChecker:
    """Periodic lightweight checks against upstream APIs."""

    async def check_tool(self, tool: ToolDefinition) -> HealthResult:
        """Send a lightweight probe to verify the upstream API is reachable.

        For GET endpoints: HEAD request or minimal GET
        For POST endpoints: OPTIONS request or dry-run with empty body
        Never sends real mutations.
        """

    async def check_all(self, tools: list[ToolDefinition]) -> HealthReport:
        """Run health checks across all tools, respecting rate limits."""

    def classify_failure(self, error: Exception) -> FailureClass:
        """Classify failures with confidence scoring.

        Returns: AUTH_EXPIRED, ENDPOINT_GONE, RATE_LIMITED,
                 SERVER_ERROR, NETWORK_UNREACHABLE, SCHEMA_CHANGED, UNKNOWN
        """
```

This integrates with the existing repair engine: when `check_all()` finds unhealthy tools, it feeds results into `RepairEngine` as a new evidence source.

**Meta-tool exposure (P1, ~150 lines):**

Add HEAL meta-tools to the existing `CaskMCPMetaMCPServer`:

```python
# Added to mcp/meta_server.py
@server.list_tools()
async def list_tools():
    return existing_tools + [
        Tool(name="toolwright_diagnose_tool", ...),
        Tool(name="toolwright_repair_tool", ...),
        Tool(name="toolwright_health_check", ...),
    ]
```

These let agents self-diagnose: "Why did my last call fail? What can I do about it?"

The Meta MCP server already exposes `caskmcp_list_actions`, `caskmcp_check_policy`, `caskmcp_get_approval_status`, `caskmcp_list_pending_approvals`, `caskmcp_get_action_details`, and `caskmcp_risk_summary`. The HEAL meta-tools follow the same pattern.

---

### 4.4 KILL — Circuit Breakers & Tool Termination

When a tool goes wrong, you can stop it. Instantly. Kill a misbehaving tool mid-request, auto-disable tools that fail repeatedly, quarantine them for investigation.

**Status: 76% complete. Moderate new work.**

#### What Exists

**Fail-closed enforcement:**
- No lockfile → no runtime (architectural invariant)
- Unapproved tools never execute
- No bypass mechanism

**Rate limiting (`core/enforce/engine.py`):**
- `BudgetTracker` — Per-minute and per-hour sliding-window tracking
- Budget rules in policy with per-tool and global limits
- Audit events on budget exhaustion

**SSRF protection (`core/network_safety.py`):**
- Private IP range blocking (RFC 1918, link-local, loopback)
- Cloud metadata endpoint blocking (169.254.169.254, etc.)
- Redirect validation with hop limits
- Host allowlist enforcement
- URL scheme validation (HTTPS only by default)

**Confirmation flow (`core/enforce/confirmation_store.py`):**
- `ConfirmationStore` — SQLite-backed challenge store
- HMAC-signed tokens with TTL
- Out-of-band grant/deny via CLI

**Dry-run mode:**
- Evaluate policy without executing upstream calls

#### What's Missing

**Circuit breaker state machine (P1, ~250 lines):**

`core/kill/breaker.py`:

```python
from enum import StrEnum
from pydantic import BaseModel

class BreakerState(StrEnum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # All calls blocked
    HALF_OPEN = "half_open" # Testing recovery

class ToolCircuitBreaker(BaseModel):
    """Per-tool circuit breaker with audit integration."""

    tool_id: str
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_at: str | None = None
    opened_at: str | None = None
    half_open_at: str | None = None

    # Configurable thresholds
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    success_threshold: int = 3  # Successes needed to close from half-open

class CircuitBreakerRegistry:
    """Manage circuit breakers for all tools."""

    def __init__(self, audit_logger: AuditLogger | None = None):
        self._breakers: dict[str, ToolCircuitBreaker] = {}
        self._audit = audit_logger

    def should_allow(self, tool_id: str) -> tuple[bool, str]:
        """Check if a tool call should proceed.

        Returns (allowed, reason).
        In OPEN state: blocked until recovery_timeout elapses, then → HALF_OPEN.
        In HALF_OPEN: allow one probe call.
        In CLOSED: always allow.
        """

    def record_success(self, tool_id: str) -> None:
        """Record a successful call.
        HALF_OPEN + enough successes → CLOSED.
        CLOSED → reset failure count.
        """

    def record_failure(self, tool_id: str, error: Exception) -> None:
        """Record a failed call.
        CLOSED + threshold exceeded → OPEN (trips the breaker).
        HALF_OPEN + failure → OPEN (re-trips).
        """

    def kill_tool(self, tool_id: str, reason: str) -> None:
        """Manually force a tool into OPEN state (operator kill switch)."""

    def enable_tool(self, tool_id: str) -> None:
        """Manually force a tool into CLOSED state (operator override)."""

    def quarantine_report(self) -> list[ToolCircuitBreaker]:
        """List all tools currently in OPEN or HALF_OPEN state."""
```

**Why build this in-house instead of using `pybreaker` or `circuitbreaker`:**

We evaluated three Python circuit breaker libraries:

| Library | Stars | Last Release | Verdict |
|---|---|---|---|
| `pybreaker` | 1.2K | v1.4.1 (2025) | Function-level decorator pattern |
| `aiobreaker` | 200 | v1.2.0 (2021) | Fork of pybreaker, stale |
| `circuitbreaker` | 600 | v2.1.3 (Mar 2025) | Clean decorator API |

**All three are designed for wrapping function calls.** They track failures on a per-function basis and raise `CircuitBreakerError` when the circuit opens. This doesn't fit our model:

1. **We need per-tool-id tracking**, not per-function. Multiple tool calls route through the same `_execute_request` method.
2. **We need audit integration.** State transitions must emit audit events with structured metadata (tool_id, failure count, reason).
3. **We need manual kill/enable.** Operators must be able to force-open a circuit (kill) or force-close it (enable) regardless of automatic state.
4. **We need serializable state.** Circuit breaker state must persist across server restarts.
5. **We need meta-tool exposure.** The circuit breaker state must be queryable via MCP meta-tools.

Building our own circuit breaker is ~250 lines with Pydantic models, which is simpler than adapting any of the libraries and adding the integration shims.

**Response size limits (P2, ~30 lines):**

Add to `_execute_request` in `mcp/server.py`:

```python
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB default

content_length = response.headers.get("content-length")
if content_length and int(content_length) > MAX_RESPONSE_BYTES:
    raise RuntimeBlockError(
        ReasonCode.DENIED_RESPONSE_TOO_LARGE,
        f"Response size {content_length} exceeds limit {MAX_RESPONSE_BYTES}",
    )
```

Note: `DENIED_RESPONSE_TOO_LARGE` already exists in `ReasonCode` enum — CaskMCP anticipated this feature.

**Meta-tool exposure (P1, ~120 lines):**

Add KILL meta-tools to `mcp/meta_server.py`:

```python
# toolwright_kill_tool — Force-open a circuit breaker
# toolwright_enable_tool — Force-close a circuit breaker
# toolwright_quarantine_report — List all quarantined tools
```

---

### 4.5 CORRECT — Human-in-the-Loop Behavioral Rules

**This is the core differentiator.** When an agent uses a tool incorrectly, the human can correct the behavior, and the correction becomes a durable rule enforced on every future call — without retraining the model or rewriting prompts. The agent learns from corrections at the *tool infrastructure* level, not the model level.

**Status: 12% complete. This is the primary new work.**

#### What Exists

The policy system (`core/enforce/engine.py`) provides **compile-time rules** that match requests by host, path, method, risk tier, and scope. These rules are generated during `cask compile` and stored in `policy.yaml`. They handle access control (allow/deny), confirmation requirements, rate budgets, and audit levels.

What they don't handle is **behavioral rules** — runtime-editable constraints on how tools are used in sequence, what parameter values are allowed, and what prerequisites must be met before calling a tool.

#### What's New

The CORRECT pillar adds a **durable behavioral rule engine** that sits between the policy engine and the proxy layer. It evaluates rules against **session history** — the sequence of tool calls in the current conversation — and produces structured violation feedback that agents can use to self-correct.

**Six rule types:**

```python
class RuleKind(StrEnum):
    PREREQUISITE = "prerequisite"   # Tool B requires Tool A first
    PROHIBITION = "prohibition"     # Never call Tool X after Tool Y
    PARAMETER = "parameter"         # Constrain parameter values
    SEQUENCE = "sequence"           # Enforce call ordering
    RATE = "rate"                   # Per-session rate limits (distinct from policy budgets)
    APPROVAL = "approval"           # Require human approval for specific patterns
```

**Rule model (`models/rule.py`, ~200 lines):**

```python
class BehavioralRule(BaseModel):
    """A runtime-editable behavioral constraint."""

    rule_id: str = Field(default_factory=lambda: f"rule_{uuid4().hex[:8]}")
    kind: RuleKind
    description: str
    enabled: bool = True
    priority: int = 100  # Lower = higher priority

    # What this rule applies to
    target_tool_ids: list[str] = []    # Empty = all tools
    target_methods: list[str] = []     # Empty = all methods
    target_hosts: list[str] = []       # Empty = all hosts

    # Rule-specific configuration
    config: dict[str, Any] = {}

    # Metadata
    created_at: str = Field(default_factory=...)
    created_by: str = "operator"

class PrerequisiteConfig(BaseModel):
    """Config for PREREQUISITE rules."""
    required_tool_ids: list[str]          # Must have called these first
    required_within_session: bool = True  # Within current session only
    required_args: dict[str, Any] = {}    # Optional: specific arg values required

class ProhibitionConfig(BaseModel):
    """Config for PROHIBITION rules."""
    after_tool_ids: list[str] = []        # Prohibited after calling these
    after_result_contains: str | None = None  # Prohibited if prior result contained this
    always: bool = False                  # Always prohibited (unconditional)

class ParameterConfig(BaseModel):
    """Config for PARAMETER rules."""
    param_name: str
    allowed_values: list[Any] = []        # Whitelist
    blocked_values: list[Any] = []        # Blacklist
    max_value: float | None = None
    min_value: float | None = None
    pattern: str | None = None            # Regex for string params

class SequenceConfig(BaseModel):
    """Config for SEQUENCE rules."""
    required_order: list[str]             # Tool IDs in required order
    strict: bool = False                  # If true, no intervening calls allowed

class SessionRateConfig(BaseModel):
    """Config for RATE rules (per-session, distinct from policy budgets)."""
    max_calls: int
    window_seconds: int | None = None     # None = entire session
    per_tool: bool = True                 # Per-tool or global

class ApprovalConfig(BaseModel):
    """Config for APPROVAL rules."""
    when_param_matches: dict[str, Any] = {}  # Trigger on specific param values
    when_after_tool: str | None = None       # Trigger after specific tool
    approval_message: str = "This action requires approval"
```

**Rule engine (`core/correct/engine.py`, ~350 lines):**

```python
class SessionHistory:
    """Track tool call history within a session."""

    def __init__(self):
        self.calls: list[SessionCall] = []

    def record(self, tool_id: str, method: str, host: str,
               params: dict, result_summary: str | None = None):
        """Record a completed tool call."""

    def has_called(self, tool_id: str, with_args: dict | None = None) -> bool:
        """Check if a tool was called (optionally with specific args)."""

    def calls_since(self, seconds: int) -> list[SessionCall]:
        """Get calls within a time window."""

    def call_count(self, tool_id: str | None = None) -> int:
        """Count calls for a tool (or all tools)."""


class RuleEngine:
    """Evaluate behavioral rules against session history."""

    def __init__(self, rules_path: Path, audit_logger: AuditLogger | None = None):
        self.rules = self._load_rules(rules_path)
        self._audit = audit_logger

    def evaluate(self, tool_id: str, method: str, host: str,
                 params: dict, session: SessionHistory) -> RuleEvaluation:
        """Evaluate all applicable rules for a tool call.

        Returns RuleEvaluation with:
          - allowed: bool
          - violations: list[RuleViolation]
          - feedback: str (agent-consumable explanation)
        """

    def add_rule(self, rule: BehavioralRule) -> BehavioralRule:
        """Add a new rule. Checks for conflicts."""

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""

    def update_rule(self, rule_id: str, updates: dict) -> BehavioralRule:
        """Update an existing rule."""

    def list_rules(self, kind: RuleKind | None = None) -> list[BehavioralRule]:
        """List rules, optionally filtered by kind."""

    def detect_conflicts(self, rule: BehavioralRule) -> list[RuleConflict]:
        """Check if a new rule conflicts with existing rules.

        Conflicts: prerequisite A→B + prohibition B→A (circular)
                   parameter whitelist + blacklist overlap
                   sequence A,B,C + sequence C,B,A
        """


class RuleViolation(BaseModel):
    """A single rule violation with structured feedback."""

    rule_id: str
    rule_kind: RuleKind
    tool_id: str
    description: str
    feedback: str  # Agent-consumable: "You must call get_user before update_user"
    severity: str  # "error" (blocked) or "warning" (logged but allowed)
    suggestion: str | None = None  # "Try calling get_user first"
```

**Rule persistence:**

Rules are stored as JSON at `.toolwright/rules.json` (or configurable path). This is consistent with the existing approach — lockfiles are YAML, policies are YAML, and all artifacts live under `.toolwright/` (replacing `.caskmcp/`).

No database. No ORM. JSON file + Pydantic validation. Rules are loaded at server startup and hot-reloaded on file change (via `watchdog` or simple mtime check).

**Integration with existing enforcement:**

The rule engine slots into the existing decision pipeline in `mcp/server.py`:

```python
# Current flow (simplified):
# 1. Resolve action from tool_id
# 2. DecisionEngine.evaluate() → ALLOW/DENY/CONFIRM
# 3. If ALLOW → _execute_request()

# New flow:
# 1. Resolve action from tool_id
# 2. DecisionEngine.evaluate() → ALLOW/DENY/CONFIRM
# 3. If ALLOW → RuleEngine.evaluate() → check behavioral rules
# 4. If ALLOW → CircuitBreaker.should_allow() → check tool health
# 5. If ALLOW → _execute_request()
# 6. Record success/failure in circuit breaker + session history
```

The key insight: **the rule engine does not replace the decision engine.** It's an additional layer. The decision engine handles access control (lockfile approval, policy evaluation). The rule engine handles behavioral constraints (prerequisites, prohibitions, parameter bounds).

**Meta-tool handlers (P1, ~200 lines):**

```python
# Added to mcp/meta_server.py or a new mcp/correct_tools.py:
# toolwright_add_rule — Create a behavioral rule
# toolwright_list_rules — List all behavioral rules
# toolwright_remove_rule — Remove a rule by ID
# toolwright_update_rule — Update an existing rule
```

These allow agents (or operators via the meta MCP server) to manage rules at runtime. The meta server is already read-only by design for governance state, but rule management is explicitly an operator action, so it requires appropriate authorization.

**CLI commands (P1, ~200 lines):**

```bash
# Rule management
toolwright rules add --kind prerequisite \
    --target update_user \
    --requires get_user \
    --description "Must fetch user before updating"

toolwright rules list [--kind prerequisite|prohibition|parameter|...]
toolwright rules remove <rule_id>
toolwright rules show <rule_id>

# Import/export
toolwright rules export --output rules.json
toolwright rules import --input rules.json
```

---

## 5. Tech Stack & Dependencies

### Core Dependencies (Already in Place)

| Package | Version | Role | Status |
|---|---|---|---|
| `click` | ≥8.1.0 | CLI framework | ✅ In use |
| `pydantic` | ≥2.0.0 | Data models, validation | ✅ In use |
| `pyyaml` | ≥6.0 | YAML parsing (policy, toolpacks) | ✅ In use |
| `httpx` | ≥0.25.0 | Async HTTP client for upstream API calls | ✅ In use |
| `rich` | ≥13.0.0 | Terminal UI, tables, progress bars | ✅ In use |
| `cryptography` | ≥43.0.0 | Ed25519 signing, AES encryption | ✅ In use |

### Optional Dependencies (Already in Place)

| Package | Extras Group | Role | Status |
|---|---|---|---|
| `mcp` | `[mcp]` | MCP SDK (stdio server) | ✅ In use |
| `playwright` | `[playwright]` | Browser-based traffic capture | ✅ In use |

### New Optional Dependencies

| Package | Extras Group | Role | Why |
|---|---|---|---|
| `authlib` | `[oauth]` | OAuth 2.0 client for upstream API auth | Mature (4.7K stars), httpx integration, MIT licensed. Handles client_credentials, auth_code+PKCE, token refresh. Avoids reimplementing RFC 6749/7636. |

### Dependencies NOT Added

| Considered | Decision | Reason |
|---|---|---|
| `pybreaker` | ❌ Build in-house | Function-level decorator pattern doesn't fit per-tool-id tracking with audit integration |
| `circuitbreaker` | ❌ Build in-house | Same issue — our breaker needs serializable state, manual kill/enable, meta-tool exposure |
| `business-rules` / `durable-rules` | ❌ Build in-house | Generic rule engines are over-engineered for 6 specific rule types. Our rules are simple predicate checks against session history, not CEP or Rete networks. |
| `sqlalchemy` | ❌ Not needed | JSON file persistence is sufficient for rules. SQLite is only used for confirmation store (already in place). |
| `fastapi` | ❌ Not needed | MCP server uses stdio transport. No HTTP server needed for v1. |
| `watchdog` | ❌ Not needed | Simple mtime check on `rules.json` is sufficient for rule hot-reload. |

### Python Version Compatibility

- **Minimum:** Python 3.11 (for StrEnum, ExceptionGroup, tomllib)
- **Tested:** Python 3.11, 3.12, 3.13 (via CI)
- **Build system:** Hatchling (already in place)
- **Package manager:** uv (recommended) or pip

### MCP SDK Compatibility

CaskMCP currently pins `mcp>=1.0.0`. The MCP Python SDK is at v1.26.0 with v2 in development. Key compatibility notes:

- **v1.x** is the stable branch. CaskMCP's `_compat.py` abstraction layer handles import differences.
- **v2.x** (pre-alpha, on `main` branch) will change transport architecture. When v2 ships, we'll update `_compat.py` — the abstraction layer exists specifically for this.
- **FastMCP 3.0** (Feb 2026) is a high-level framework built on the MCP SDK. It's nice for simple servers but overkill for Toolwright, which needs low-level control over tool registration, decision routing, and audit logging. We continue using the low-level `Server` API directly.

---

## 6. Migration Strategy: CaskMCP → Toolwright

### Phase 1: Rename (Non-Breaking)

**Package rename:** `caskmcp` → `toolwright`

```python
# pyproject.toml
[project]
name = "toolwright"
# ...
[project.scripts]
toolwright = "toolwright.cli.main:cli"
tw = "toolwright.cli.main:cli"          # Short alias
cask = "toolwright.cli.main:cli"        # Backward compat
caskmcp = "toolwright.cli.main:cli"     # Backward compat
```

**Directory rename:** `caskmcp/` → `toolwright/`

**Data directory rename:** `.caskmcp/` → `.toolwright/` with automatic migration:

```python
# toolwright/core/init/__init__.py
def migrate_data_directory():
    """Auto-migrate .caskmcp/ → .toolwright/ on first run."""
    old = Path(".caskmcp")
    new = Path(".toolwright")
    if old.exists() and not new.exists():
        old.rename(new)
        # Symlink for backward compatibility
        old.symlink_to(new)
```

**PyPI:** Publish `toolwright` as a new package. The old `caskmcp` package gets a final release that depends on `toolwright` (re-export shim).

### Phase 2: Naming Conventions

All internal references to "caskmcp" or "cask" are renamed:

| Old | New |
|---|---|
| `CaskMCPMCPServer` | `ToolwrightMCPServer` |
| `CaskMCPMetaMCPServer` | `ToolwrightMetaMCPServer` |
| `caskmcp_list_actions` | `toolwright_list_actions` |
| `caskmcp_check_policy` | `toolwright_check_policy` |
| `CASKMCP_APPROVERS` | `TOOLWRIGHT_APPROVERS` |
| `.caskmcp/` | `.toolwright/` |
| `caskmcp.lock.yaml` | `toolwright.lock.yaml` |

### Phase 3: User-Agent & Branding

```python
# toolwright/branding.py
PRODUCT_NAME = "Toolwright"
USER_AGENT = "Toolwright/1.0"
CLI_NAME = "toolwright"
CLI_ALIAS = "tw"
```

---

## 7. Implementation Plan

### Sprint 1: CORRECT Pillar (Week 1-2)

**Goal:** Behavioral rule engine with full test coverage.

| Task | Est. Lines | File(s) |
|---|---|---|
| Rule models | 200 | `models/rule.py` |
| Rule engine (evaluation + CRUD + persistence) | 350 | `core/correct/engine.py` |
| Session history tracker | 100 | `core/correct/session.py` |
| Conflict detection | 80 | `core/correct/conflicts.py` |
| Violation feedback generator | 60 | `core/correct/feedback.py` |
| Integration with MCP server | 80 | `mcp/server.py` (modify) |
| CLI commands (rules add/list/remove/show/export/import) | 200 | `cli/rules.py` |
| Tests | 600 | `tests/test_rules*.py` |
| **Subtotal** | **~1,670** | |

**Acceptance criteria:**
- All six rule types evaluate correctly against session history
- Conflict detection catches circular prerequisite/prohibition
- Violation feedback is agent-consumable (clear, actionable text)
- Rules persist across server restarts
- CLI CRUD works end-to-end

### Sprint 2: KILL Pillar + Meta-Tools (Week 3)

**Goal:** Circuit breaker state machine, response size limits, all meta-tool handlers.

| Task | Est. Lines | File(s) |
|---|---|---|
| Circuit breaker state machine | 250 | `core/kill/breaker.py` |
| Response size limits | 30 | `mcp/server.py` (modify) |
| HEAL meta-tools | 150 | `mcp/meta_server.py` (modify) |
| KILL meta-tools | 120 | `mcp/meta_server.py` (modify) |
| CORRECT meta-tools | 200 | `mcp/meta_server.py` (modify) |
| CLI commands (kill, enable, quarantine, health) | 200 | `cli/kill.py`, `cli/health.py` |
| Integration with MCP server | 60 | `mcp/server.py` (modify) |
| Tests | 600 | `tests/test_kill*.py`, `tests/test_meta*.py` |
| **Subtotal** | **~1,610** | |

### Sprint 3: HEAL Hardening + Rename (Week 4)

**Goal:** Proactive health checker, CaskMCP → Toolwright rename, OAuth optional dependency.

| Task | Est. Lines | File(s) |
|---|---|---|
| Proactive health checker | 200 | `core/health/checker.py` |
| OAuth credential provider | 300 | `core/auth/oauth.py` |
| CaskMCP → Toolwright rename | ~0 (find-replace) | All files |
| Data directory migration | 50 | `core/init/__init__.py` |
| PyPI re-publish | 0 | `pyproject.toml` |
| Documentation update | 200 | `README.md`, `docs/` |
| Tests | 400 | `tests/test_health*.py`, `tests/test_oauth*.py` |
| **Subtotal** | **~1,150** | |

### Sprint 4: Polish + v1.0 (Week 5)

| Task | Description |
|---|---|
| Integration testing | Full end-to-end: connect → use → correct → break → heal → kill |
| Performance | Rule evaluation benchmarks (target: <5ms per call) |
| Documentation | Updated user guide, architecture doc, rule guide |
| Hash-chained audit | Optional hardening (if time) |
| Release | Toolwright v1.0 on PyPI |

### Total New Code Summary

| Category | Lines |
|---|---|
| Source code (new modules) | ~2,650 |
| Tests | ~1,600 |
| Documentation + config | ~200 |
| **Total net new** | **~4,450** |

Against a 57,500-line codebase, this is an **8% increment** to reach feature completeness.

---

## 8. Open-Source Library Evaluation

### Used

| Library | Purpose | Why This One |
|---|---|---|
| `authlib` | OAuth 2.0 client flows for upstream API auth | Mature (4.7K stars, MIT), native httpx async client, covers client_credentials + auth_code + PKCE + refresh. Alternative: `requests-oauthlib` (sync only, no httpx). |

### Considered But Rejected

| Library | Purpose | Why Not |
|---|---|---|
| `pybreaker` | Circuit breaker | Decorator pattern for function-level tracking. Our breaker needs per-tool-id tracking, audit integration, manual kill/enable, serializable state, meta-tool exposure. Custom implementation is ~250 lines. |
| `circuitbreaker` | Circuit breaker | Same issues as pybreaker. Clean API but wrong abstraction level. |
| `aiobreaker` | Async circuit breaker | Fork of pybreaker, last release 2021. Stale. |
| `business-rules` | Rule engine | Generic predicate-action engine. Over-engineered for our 6 specific rule types with session history. Would add complexity without benefit. |
| `durable-rules` | Rule engine with Rete | Enterprise rule engine using C extension. Massive overkill, adds C compilation dependency, breaks `pip install` simplicity. |
| `rule-engine` | Simple rule evaluation | Too simple — no persistence, no session tracking, no conflict detection. |
| `sqlalchemy` | Database ORM | Our storage needs are simple: JSON files for rules, YAML for policies, SQLite for confirmations (already using stdlib `sqlite3`). |
| `fastapi` | HTTP server | MCP transport is stdio. No HTTP server needed. If we later support Streamable HTTP transport, we'd use the MCP SDK's built-in server, not FastAPI. |
| `celery` / `dramatiq` | Background tasks | Health checks run in-process. No background job system needed for v1. |

### Key Design Principle

> **Every dependency must clear the bar: does it solve a complex, well-defined problem better than 200 lines of custom code?**

For Toolwright, only `authlib` clears this bar. OAuth 2.0 is genuinely complex (token lifecycle, PKCE, refresh, multiple grant types) and authlib has years of battle-testing. Everything else — circuit breakers, rule engines, session tracking — is better built in-house because our requirements are domain-specific and the integrations (audit logging, meta-tools, serialization) dominate the implementation.

---

## Appendix A: Existing Test Coverage

The test suite (24,944 lines across 90+ test files) covers:

| Area | Key Test Files | Focus |
|---|---|---|
| Approval & signing | `test_approval.py` (26K), `test_approval_signing.py` | Lockfile CRUD, Ed25519 sign/verify, approval status transitions |
| Compilation | `test_compile.py` (32K), `test_compile_cli.py` | Tool manifest generation, schema inference, risk classification |
| Capture | `test_har_parser.py`, `test_otel_parser.py`, `test_openapi_parser.py`, `test_playwright_capture.py` | All five capture sources |
| Enforcement | `test_enforce_gateway.py` (29K), `test_enforcer.py`, `test_decision_engine.py` (20K) | Policy evaluation, decision engine, budget tracking |
| Network safety | `test_network_safety.py` (11K) | SSRF blocking, private IP ranges, redirect validation |
| Drift | `test_drift.py` (20K) | Schema drift detection, severity classification |
| Repair | `test_repair_engine.py` (36K), `test_repair_cli.py` | Diagnosis, patch generation, safety classification |
| MCP server | `test_mcp.py` (24K), `test_mcp_cli.py`, `test_meta_mcp.py` | Tool dispatch, decision routing, meta-tool responses |
| Proposals | `test_proposals.py`, `test_proposal_compiler.py`, `test_proposal_publisher.py` | Agent draft proposal lifecycle |
| Verification | `test_verify_engine.py`, `test_verify_replay_core.py`, `test_verify_outcomes_core.py` | Contract validation, replay, outcomes |
| UI flows | `test_ui_repair_flow.py` (28K), `test_ui_gate_review.py`, `test_ui_wizard.py` | Interactive TUI workflows |

This test suite provides a strong regression safety net for the Toolwright migration.

---

## Appendix B: MCP Specification Alignment

### Supported (Current)

| MCP Feature | Status |
|---|---|
| Tools (list, call) | ✅ Full support |
| stdio transport | ✅ Full support |
| `tools/list_changed` notifications | ✅ Supported |
| Dynamic tool registry | ✅ Supported |

### Planned (Post-v1.0)

| MCP Feature | Priority | Notes |
|---|---|---|
| Streamable HTTP transport | P2 | Required for remote MCP servers. Will use MCP SDK v2 transport layer. |
| OAuth 2.0 (MCP client → Toolwright server) | P3 | Only relevant for Streamable HTTP. Not applicable to stdio. |
| Resources | P3 | Expose governance state as MCP Resources (read-only). |
| Prompts | P3 | Pre-built prompts for common governance queries. |
| Elicitations | P2 | URL-mode elicitation for credential collection (MCP spec 2025-11-25). |
| Structured output | P3 | JSON Schema output validation (MCP spec 2025-06-18). |
| Tasks | P3 | Durable request tracking for long-running operations. |

### Design Decision: Low-Level Server API

Toolwright uses the MCP SDK's low-level `Server` class, not the high-level `FastMCP` framework. This is deliberate:

1. **Custom tool registration** — Tools are compiled from API traffic, not declared via decorators.
2. **Decision routing** — Every tool call passes through the decision engine before dispatch.
3. **Dynamic updates** — Tools can be added/removed at runtime via proposals.
4. **Audit integration** — Every call is logged with structured metadata.

FastMCP's decorator-based API (`@mcp.tool()`) is designed for static tool definitions. It would require extensive workarounds to support Toolwright's dynamic, governed tool model.

---

## Appendix C: Configuration Reference

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TOOLWRIGHT_ROOT` | `.toolwright/` | Root directory for all state |
| `TOOLWRIGHT_APPROVERS` | (none) | Comma-separated list of allowed approver identities |
| `TOOLWRIGHT_LOG_LEVEL` | `INFO` | Logging verbosity |
| `TOOLWRIGHT_MAX_RESPONSE_BYTES` | `10485760` (10MB) | Maximum upstream response size |
| `TOOLWRIGHT_CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `TOOLWRIGHT_CIRCUIT_BREAKER_TIMEOUT` | `60` | Seconds before half-open probe |

### File Layout

```
.toolwright/                      # Project root (was .caskmcp/)
├── toolpacks/                    # Compiled toolpacks
│   └── <id>/
│       ├── toolpack.yaml         # Manifest pointing to all artifacts
│       ├── tools.json            # Compiled tool definitions
│       ├── policy.yaml           # Enforcement policy
│       ├── contracts.yaml        # OpenAPI 3.1 contract
│       ├── baseline.json         # Drift detection baseline
│       ├── toolsets.yaml         # Named toolsets
│       └── toolwright.lock.yaml  # Approval lockfile
├── captures/                     # Raw captured traffic
├── baselines/                    # Baseline snapshots
├── reports/                      # Diff, drift, compliance reports
├── evidence/                     # Verification evidence bundles
├── repairs/                      # Repair diagnosis + patch outputs
├── drafts/                       # Agent draft proposals
├── scopes/                       # Custom scope definitions
├── rules.json                    # NEW: Behavioral rules
├── state/
│   ├── keys/                     # Ed25519 keypairs + trust store
│   ├── confirmations.db          # SQLite confirmation store
│   ├── breakers.json             # NEW: Circuit breaker state
│   └── audit.jsonl               # Audit log
└── config.yaml                   # Project configuration
```
