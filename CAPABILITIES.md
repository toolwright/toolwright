# Capabilities Registry

> Canonical map of existing, user-visible capabilities. No roadmap items.
> Every entry includes file paths and entry points. Use stable IDs: `CAP-<AREA>-###`.

---

## CONNECT -- Self-Expanding Toolkit

### CAP-CONNECT-001: Multi-Source API Capture

Discover and capture API traffic from HAR files, OpenAPI specs, OTEL traces, browser automation, and WebMCP.

- `toolwright/core/capture/har_parser.py` -> `HARParser`
- `toolwright/core/capture/openapi_parser.py` -> `OpenAPIParser`
- `toolwright/core/capture/otel_parser.py` -> `OTELParser`
- `toolwright/core/capture/playwright_capture.py` -> Playwright browser capture
- `toolwright/core/capture/webmcp_capture.py` -> WebMCP capture
- CLI: `toolwright capture import <file_or_url>`

### CAP-CONNECT-002: Traffic Redaction

Redact sensitive data (tokens, PII, API keys, cookies) from captured traffic based on configurable profiles.

- `toolwright/core/capture/redactor.py` -> `Redactor`
- `toolwright/core/capture/redaction_profiles.py` -> `RedactionProfile`
- Integrated into all capture commands

### CAP-CONNECT-003: Tool Manifest Compilation

Generate `tools.json` (tool definitions with schemas, risk tiers, tags) from captured API specifications.

- `toolwright/core/compile/tools.py` -> `ToolManifestGenerator`
- CLI: `toolwright compile --capture <id>`

### CAP-CONNECT-004: Automatic Risk Classification

Classify tools by risk tier (low/medium/high/critical) based on HTTP method, path patterns, and keywords.

- `toolwright/core/risk_keywords.py` -> Risk keyword patterns
- `toolwright/core/enrich/llm_classifier.py` -> Optional LLM enrichment
- Used by: CAP-CONNECT-003

### CAP-CONNECT-005: Authentication Detection

Automatically detect and extract auth patterns (Bearer, OAuth, API keys) from captured traffic. Results are stored as `ToolpackAuthRequirement` concrete models in `toolpack.yaml` with pre-computed env var names.

- `toolwright/core/auth/detector.py` -> `detect_auth_requirements()`
- `toolwright/core/toolpack.py` -> `ToolpackAuthRequirement`, `build_auth_requirements()`
- `toolwright/core/auth/provider.py` -> `TokenProvider` (protocol)
- `toolwright/core/auth/profiles.py` -> Auth profiles
- CLI: `toolwright auth`, `toolwright auth check`
- Auth display: shown in `mint` output after compile, with env var export suggestions

### CAP-CONNECT-011: OAuth2 Credential Provider

Per-host OAuth2 client-credentials token manager with automatic refresh, proactive expiry margin, and in-memory caching.

- `toolwright/core/auth/oauth.py` -> `OAuthCredentialProvider`, `OAuthConfig`, `OAuthError`
- Methods: `configure(host, config)`, `get_token(host)`, `refresh_token(host)`, `clear_tokens()`, `configured_hosts()`
- Optional dependency: `pip install "toolwright[oauth]"`
- Token lifecycle: fetch → cache → proactive refresh (configurable `expiry_margin_seconds`)

### CAP-CONNECT-012: Draft Toolpack Creation

Create draft toolpacks from discovered `CaptureSession` data (e.g., from OpenAPI discovery). Draft toolpacks are staged in `.toolwright/drafts/<id>/` for human review before promotion. Drafts are NOT loaded by `toolwright serve`.

- `toolwright/core/discover/draft_toolpack.py` -> `DraftToolpackCreator`
- Methods: `create(session, label)`, `list_drafts()`, `get_draft_path(draft_id)`
- Outputs: `toolpack.yaml` (with `draft: true`), `tools.json` (action manifest), `manifest.json` (metadata)
- Action generation: deduplicates by method+path, auto-names (e.g., `get_users`), assigns risk tiers
- Tests: `tests/test_draft_toolpack.py`

### CAP-CONNECT-006: One-Command API Onboarding (Mint)

Single command to capture API traffic via browser, compile tools, and publish a toolpack.

- `toolwright/cli/mint.py` -> `mint()`
- CLI: `toolwright mint <url> -a <api_domain>`

### CAP-CONNECT-007: MCP Server Provisioning

Start a governed MCP server on stdio transport serving compiled tools. Supports auth via env vars, per-host auth, and CLI flag. Toolpack path auto-resolves when omitted.

- `toolwright/mcp/server.py` -> `ToolwrightMCPServer`, `_resolve_auth_for_host()`
- `toolwright/cli/commands_mcp.py` -> `run_mcp_serve()`, auto-resolution via `resolve_toolpack_path()`
- CLI: `toolwright serve [--toolpack <path>] [--auth "Bearer <token>"]`
- Auth priority: `--auth` flag > `TOOLWRIGHT_AUTH_<NORMALIZED_HOST>` env var > `TOOLWRIGHT_AUTH_HEADER` env var > None
- Per-host env var naming: replace dots/hyphens with underscores, uppercase (e.g., `api.github.com` -> `TOOLWRIGHT_AUTH_API_GITHUB_COM`)

### CAP-CONNECT-008: Toolset Scoping

Create named subsets of tools for different use cases (readonly, admin, operator).

- `toolwright/core/compile/toolsets.py` -> `ToolsetGenerator`
- `toolwright/core/scope/engine.py` -> Scope engine
- `toolwright/core/scope/inference.py` -> Scope inference
- `toolwright/models/scope.py` -> Scope models
- CLI: `toolwright scope`

### CAP-CONNECT-009: MCP Configuration Generation

Generate MCP client configuration for Claude Desktop, Cursor, and other MCP clients.

- `toolwright/cli/config.py` -> Config command
- CLI: `toolwright config --toolpack <path>`

### CAP-CONNECT-010: Project Initialization

Initialize a new toolwright project with directory structure and guided setup.

- `toolwright/core/init/detector.py` -> Project detection
- `toolwright/cli/init.py` -> `run_init()`
- CLI: `toolwright init`

---

## GOVERN -- Safety & Trust Layer

### CAP-GOVERN-001: Cryptographic Approval Signing (Ed25519)

Sign tool approvals with Ed25519 keys to create tamper-proof approval records.

- `toolwright/core/approval/signing.py` -> Signing logic
- `toolwright/core/approval/lockfile.py` -> Lockfile format

### CAP-GOVERN-002: Lockfile Management

Maintain persistent approval state (pending/approved/rejected) with signatures and metadata.

- `toolwright/core/approval/lockfile.py` -> `LockfileManager`, `ToolApproval`
- Files: `toolwright.lock.yaml`, `toolwright.lock.pending.yaml`

### CAP-GOVERN-003: Tool Approval Workflow (Gate)

Review, approve, block, or conditionally approve tools before use. All gate commands accept `--toolpack` for unified path resolution.

- `toolwright/cli/approve.py` -> Approval logic, `_resolve_gate_paths()` for toolpack resolution
- `toolwright/cli/commands_approval.py` -> Gate command group with `--toolpack` option on all subcommands
- `toolwright/ui/flows/gate_review.py` -> Interactive approval flow
- CLI:
  - `toolwright gate sync --toolpack <path>` -- Sync lockfile with manifest
  - `toolwright gate status --toolpack <path>` -- List approval states
  - `toolwright gate allow --toolpack <path>` -- Approve tools
  - `toolwright gate block --toolpack <path>` -- Block tools
  - `toolwright gate check --toolpack <path>` -- CI gate (exit 0 if all approved, suggests approval command on failure)

### CAP-GOVERN-004: Policy-Based Enforcement

Define and enforce fine-grained rules controlling tool access (allow/deny/confirm/budget/redact).

- `toolwright/core/compile/policy.py` -> `PolicyGenerator`
- `toolwright/core/enforce/engine.py` -> `PolicyEngine`
- `toolwright/models/policy.py` -> Policy models
- Files: `policy.yaml`

### CAP-GOVERN-005: Runtime Decision Engine

Evaluate runtime tool invocations against lockfile, policy, and approval signatures. Returns allow/deny/confirm with reason codes.

- `toolwright/core/enforce/decision_engine.py` -> `DecisionEngine`
- `toolwright/core/enforce/enforcer.py` -> `Enforcer`
- `toolwright/models/decision.py` -> `DecisionType`, `ReasonCode`

### CAP-GOVERN-006: Structured Audit Logging

Log all approval/denial/execution decisions with reason codes, timestamps, and full context.

- `toolwright/core/audit/logger.py` -> `AuditLogger`
- `toolwright/core/audit/decision_trace.py` -> Decision traces

### CAP-GOVERN-007: Network Safety Controls

Prevent SSRF attacks, validate URLs, restrict private CIDR access, enforce redirect allowlists.

- `toolwright/core/network_safety.py` -> Network validation
- CLI flags: `--allow-private-cidr`, `--allow-redirects`

### CAP-GOVERN-008: Integrity Verification

Compute and verify SHA256 digests of lockfiles, policies, and toolpacks.

- `toolwright/core/approval/integrity.py` -> Digest functions
- `toolwright/utils/digests.py` -> Hash utilities

### CAP-GOVERN-009: Approval Snapshot & Re-seal

Materialize approval baselines and re-sign approvals for maintenance/migration.

- `toolwright/core/approval/snapshot.py` -> Snapshot generation
- `toolwright/cli/approve.py` -> `run_approve_snapshot()`, `run_approve_resign()`
- CLI: `toolwright gate snapshot`, `toolwright gate reseal`

### CAP-GOVERN-010: EU AI Act Compliance Reporting

Generate compliance reports for regulated high-risk AI systems.

- `toolwright/core/compliance/report.py` -> Report generation
- CLI: `toolwright compliance report`

### CAP-GOVERN-011: Confirmation Gate (Out-of-Band)

Require explicit human confirmation for sensitive tool calls via single-use token system.

- `toolwright/core/enforce/confirmation_store.py` -> `ConfirmationStore`
- `toolwright/cli/confirm.py` -> Confirmation CLI
- CLI: `toolwright confirm grant <token_id>`

---

## HEAL -- Self-Repairing Tools

### CAP-HEAL-001: Drift Detection

Detect schema changes between API captures (breaking changes, new endpoints, deprecated paths).

- `toolwright/core/drift/engine.py` -> `DriftEngine`
- `toolwright/models/drift.py` -> `DriftItem`, `DriftReport`
- CLI: `toolwright drift --capture-a <old> --capture-b <new>`

### CAP-HEAL-002: Repair Engine (Diagnosis + Patch)

Diagnose tool failures and generate repair patches.

- `toolwright/core/repair/engine.py` -> `RepairEngine`
- `toolwright/models/repair.py` -> `DiagnosisItem`, `PatchItem`
- CLI: `toolwright repair --toolpack <path>`

### CAP-HEAL-003: Interactive Repair Flow

Guided wizard for diagnosing and fixing broken tools.

- `toolwright/ui/flows/repair.py` -> Repair flow UI
- CLI: `toolwright repair` (interactive mode)

### CAP-HEAL-004: Verification & Evidence Bundles

Replay tool calls, verify outputs against contracts, bundle proof artifacts.

- `toolwright/core/verify/engine.py` -> `VerifyEngine`
- `toolwright/core/verify/evidence.py` -> Evidence bundling
- `toolwright/core/verify/contracts.py` -> Contract validation
- `toolwright/core/verify/replay.py` -> Replay engine
- CLI: `toolwright verify`

### CAP-HEAL-005: Contract-Based Testing

Define input/output contracts for tools and validate against live calls.

- `toolwright/core/compile/contract.py` -> `ContractCompiler`
- `toolwright/core/verify/contracts.py` -> Contract validation
- `toolwright/models/verify.py` -> Verification models

### CAP-HEAL-006: Automated Proposal Generation

Generate repair proposals based on detected failures.

- `toolwright/core/proposal/engine.py` -> `ProposalEngine`
- `toolwright/core/proposal/compiler.py` -> Proposal compilation
- `toolwright/core/proposal/publisher.py` -> Proposal publishing
- CLI: `toolwright propose`

### CAP-HEAL-007: Endpoint Health Checker

Non-mutating health probes for API endpoints. Uses HEAD for GET endpoints and OPTIONS for write endpoints to avoid side effects. Classifies failures into 7 categories with concurrent multi-tool probing. Integrated into the meta-server (`toolwright_health_check` and `toolwright_diagnose_tool` meta-tools) and available as a standalone CLI command.

- `toolwright/core/health/__init__.py` -> Package init
- `toolwright/core/health/checker.py` -> `HealthChecker`, `HealthResult`, `FailureClass`
- `toolwright/mcp/meta_server.py` -> `_health_check()`, `_diagnose_tool()` (endpoint probing integration)
- `toolwright/cli/main.py` -> `health` command (CLI entry point)
- Methods: `check_tool(action)`, `check_all(actions)`, `classify_failure(status_code, error)`
- Failure classes: `auth_expired`, `endpoint_gone`, `rate_limited`, `server_error`, `network_unreachable`, `schema_changed`, `unknown`
- Configurable: `scheme`, `timeout_seconds`, `max_concurrent`
- CLI: `toolwright health --tools <path>` — probes all endpoints, exits 0 if all healthy, 1 if any unhealthy

### CAP-HEAL-008: Reconciliation Loop (Level-Triggered)

Kubernetes-style async reconciliation loop that continuously monitors tool health, detects API drift, and orchestrates repairs. Runs as a background asyncio.Task alongside the MCP server.

- `toolwright/core/reconcile/loop.py` -> `ReconcileLoop`
- `toolwright/core/reconcile/prober.py` -> `HealthProber` (wraps HealthChecker with scheduling + backoff)
- `toolwright/core/reconcile/event_log.py` -> `ReconcileEventLog` (JSONL append-only log)
- `toolwright/core/reconcile/differ.py` -> `DriftDiffer` (wraps DriftEngine)
- `toolwright/core/reconcile/rediscovery.py` -> `EndpointRediscovery`
- `toolwright/models/reconcile.py` -> `ReconcileState`, `ToolReconcileState`, `WatchConfig`, `ReconcileEvent`
- State: `.toolwright/state/reconcile.json`, `.toolwright/state/reconcile.log.jsonl`
- CLI: `toolwright serve --watch [--watch-config <path>]`
- CLI: `toolwright watch status`, `toolwright watch log [--tool X] [--last N]`
- Probe intervals configurable per risk tier (critical: 120s, high: 300s, medium: 600s, low: 1800s)
- Exponential backoff for unhealthy tools, fail-closed on errors

### CAP-HEAL-009: Toolpack Versioning (Snapshots & Rollback)

Timestamped snapshots of toolpack files with rollback support. Pruning respects snapshots referenced by pending repairs or active repair plans.

- `toolwright/core/reconcile/versioner.py` -> `ToolpackVersioner`
- Methods: `snapshot(label)`, `rollback(snapshot_id)`, `list_snapshots()`, `prune()`
- Files: `.toolwright/snapshots/<id>/` (tools.json, policy.yaml, lockfile, toolpack.yaml, manifest.json)
- Pruning: keeps max 20 snapshots; protects snapshots referenced in `reconcile.json` or `repair_plan.json`
- CLI: `toolwright snapshots`, `toolwright rollback <snapshot_id>`
- Tests: `tests/test_toolpack_versioner.py`, `tests/test_snapshots_cli.py`

### CAP-HEAL-010: Repair Plan/Apply (Terraform-Style)

Terraform-style `plan` then `apply` workflow for tool repairs. Groups patches by safety tier with color-coded output.

- `toolwright/cli/commands_repair.py` -> `register_repair_commands()`
- CLI: `toolwright repair plan [--toolpack <path>]`, `toolwright repair apply [--toolpack <path>]`
- Plan output: SAFE (green), APPROVAL_REQUIRED (yellow), MANUAL (red) patches with CLI commands
- Plan persistence: `.toolwright/state/repair_plan.json` with `generated_at` staleness check
- Tests: `tests/test_repair_plan_apply.py`

### CAP-HEAL-011: Auto-Repair (Three-Tier Policy)

Programmatic patch application with three-tier auto-heal policy. Snapshots before any repair and rolls back on failure (fail-closed).

- `toolwright/core/repair/applier.py` -> `RepairApplier`, `PatchResult`, `ApplyResult`
- Policy tiers: OFF (nothing auto-applies), SAFE (only PatchKind.SAFE), ALL (SAFE + APPROVAL_REQUIRED)
- Action dispatch: VERIFY_CONTRACTS, VERIFY_PROVENANCE (safe); GATE_ALLOW, GATE_SYNC, GATE_RESEAL (approval); INVESTIGATE, RE_MINT, REVIEW_POLICY, ADD_HOST (manual)
- Wired into ReconcileLoop: `toolwright/core/reconcile/loop.py` -> `_handle_repair()`
- CLI: `toolwright serve --watch --auto-heal <off|safe|all>`
- Config: `.toolwright/watch.yaml` -> `auto_heal` field
- Tests: `tests/test_repair_applier.py`

---

## KILL -- Circuit Breakers & Safety Gates

### CAP-KILL-001: Fail-Closed Enforcement

Default deny stance -- tools blocked unless explicitly approved in lockfile.

- Built into `toolwright/core/enforce/decision_engine.py` via `ApprovalStatus` checks

### CAP-KILL-002: Timeout Enforcement

Cancel requests that exceed execution timeout.

- `toolwright/mcp/server.py` -> httpx client timeout (30s default)

### CAP-KILL-003: Dry-Run Mode

Evaluate policy and simulate calls without executing upstream HTTP requests.

- `toolwright/mcp/server.py` -> Dry-run execution path
- CLI: `toolwright serve --dry-run`

### CAP-KILL-004: Response Size Limits

Block responses exceeding a configurable byte limit to prevent memory exhaustion.

- `toolwright/mcp/server.py` -> `_check_response_size()`, `get_max_response_bytes()`, `DEFAULT_MAX_RESPONSE_BYTES`
- `toolwright/models/decision.py` -> `ReasonCode.DENIED_RESPONSE_TOO_LARGE`
- ENV: `TOOLWRIGHT_MAX_RESPONSE_BYTES` (default 10 MB, 0 = unlimited)

### CAP-KILL-005: Path Blocklist

Block known non-API paths (static assets, health checks, etc.) from tool discovery.

- `toolwright/core/capture/path_blocklist.py` -> Path blocklist patterns

### CAP-KILL-006: Circuit Breaker State Machine

Per-tool circuit breaker (CLOSED / OPEN / HALF_OPEN) that trips after consecutive failures and auto-recovers after a timeout.

- `toolwright/core/kill/breaker.py` -> `CircuitBreakerRegistry`, `ToolCircuitBreaker`, `BreakerState`
- State persisted to `.toolwright/state/circuit_breakers.json` (atomic writes)
- Configurable: `failure_threshold` (default 5), `recovery_timeout_seconds` (default 60), `success_threshold` (default 3)

### CAP-KILL-007: Manual Kill / Enable

Force a tool's circuit breaker OPEN (kill) or CLOSED (enable) via CLI or API, with manual overrides that never auto-recover.

- `toolwright/core/kill/breaker.py` -> `kill_tool()`, `enable_tool()`
- CLI:
  - `toolwright kill <tool_id> --reason "..."`
  - `toolwright enable <tool_id>`

### CAP-KILL-008: Quarantine Report

List all tools with tripped or manually killed circuit breakers.

- `toolwright/core/kill/breaker.py` -> `quarantine_report()`
- CLI: `toolwright quarantine`

### CAP-KILL-009: Circuit Breaker MCP Integration

Integrate circuit breaker checks into the MCP server request pipeline -- block tool calls when breaker is OPEN, record successes/failures after execution.

- `toolwright/mcp/server.py` -> Circuit breaker check in `handle_call_tool`, success/failure recording
- `toolwright/models/decision.py` -> `ReasonCode.DENIED_CIRCUIT_BREAKER_OPEN`
- CLI: `toolwright serve --circuit-breaker-path <path>`

### CAP-KILL-010: Breaker Status Inspection

View the current state of a specific tool's circuit breaker (state, failure count, last error).

- `toolwright/cli/commands_kill.py` -> `breaker_status()`
- CLI: `toolwright breaker-status <tool_id>`

---

## CORRECT -- Behavioral Rules & Runtime Constraints

### CAP-CORRECT-001: Compile-Time Policy Rules

Define static access control rules (allow/deny/confirm/budget/audit/redact) that are compiled into `policy.yaml`.

- `toolwright/core/compile/policy.py` -> Policy generation
- `toolwright/models/policy.py` -> Policy models
- Files: `policy.yaml`

### CAP-CORRECT-002: Behavioral Rule Engine

Evaluate runtime tool invocations against 6 rule types (prerequisite, prohibition, parameter, sequence, rate, approval) with hot-reload, CRUD, and JSON persistence.

- `toolwright/core/correct/engine.py` -> `RuleEngine`
- `toolwright/models/rule.py` -> `BehavioralRule`, `RuleKind`, `RuleViolation`, `RuleEvaluation`
- Files: `.toolwright/rules.json`

### CAP-CORRECT-003: Session History Tracking

Track tool invocations within a session for prerequisite, sequence, and rate rule evaluation.

- `toolwright/core/correct/session.py` -> `SessionHistory`
- Methods: `record()`, `has_called()`, `calls_since()`, `call_count()`

### CAP-CORRECT-004: Rule Conflict Detection

Detect contradictions between rules before adding them (circular prerequisites, parameter whitelist/blacklist overlap, contradictory sequences).

- `toolwright/core/correct/conflicts.py` -> `detect_conflicts()`
- `toolwright/models/rule.py` -> `RuleConflict`

### CAP-CORRECT-005: Violation Feedback Generation

Generate structured, agent-consumable feedback when behavioral rules are violated, with numbered violations and remediation suggestions.

- `toolwright/core/correct/feedback.py` -> `generate_feedback()`

### CAP-CORRECT-006: MCP Server Rule Enforcement

Integrate behavioral rule checks into the MCP server request pipeline (between policy ALLOW and HTTP execution), with session recording after successful calls.

- `toolwright/mcp/server.py` -> Rule check in `handle_call_tool`, session recording after `_execute_request`
- `toolwright/models/decision.py` -> `ReasonCode.DENIED_BEHAVIORAL_RULE`
- CLI: `toolwright serve --rules-path <path>`

### CAP-CORRECT-008: Agent Rule Suggestion (suggest_rule)

Allow agents to propose new behavioral rules as DRAFT. Agent-suggested rules are created with `status=DRAFT` and `created_by="agent"`, ensuring agents cannot self-activate rules -- only humans can promote them to ACTIVE via `toolwright rules activate`.

- `toolwright/mcp/meta_server.py` -> `_suggest_rule()`, `toolwright_suggest_rule` tool definition
- Parameters: `kind`, `description`, `config`, `target_tool_ids` (optional)
- Output: concise plain-text with rule ID, DRAFT status, and next-step guidance
- Tests: `tests/test_suggest_rule_meta.py`

### CAP-CORRECT-009: Rule Status Lifecycle (DRAFT/ACTIVE/DISABLED)

Three-state lifecycle for behavioral rules enabling agent suggestion and human activation. Rules default to ACTIVE; agent-suggested rules start as DRAFT. Backward-compatible migration from legacy `enabled` boolean.

- `toolwright/models/rule.py` -> `RuleStatus` enum (DRAFT, ACTIVE, DISABLED), `BehavioralRule._migrate_enabled_to_status()` model validator
- `toolwright/core/correct/engine.py` -> `_applicable_rules()` filters on `status == ACTIVE`
- CLI: `toolwright rules drafts`, `toolwright rules activate <id>`, `toolwright rules disable <id>`
- Tests: `tests/test_rule_status_lifecycle.py`, `tests/test_rules_lifecycle_cli.py`

### CAP-CORRECT-007: Rules CLI Management

CLI commands for creating, listing, removing, inspecting, exporting, and importing behavioral rules.

- `toolwright/cli/commands_rules.py` -> `register_rules_commands()`
- CLI:
  - `toolwright rules add --kind <kind> --target <tool_id> --description "..."`
  - `toolwright rules list [--kind <kind>]`
  - `toolwright rules remove <rule_id>`
  - `toolwright rules show <rule_id>`
  - `toolwright rules export --output <file>`
  - `toolwright rules import --input <file>`
  - `toolwright rules drafts` -- list DRAFT rules
  - `toolwright rules activate <rule_id>` -- DRAFT/DISABLED → ACTIVE
  - `toolwright rules disable <rule_id>` -- ACTIVE → DISABLED

---

## Cross-Cutting Capabilities

### CAP-CROSS-001: Toolpack Artifact Resolution

Resolve `toolpack.yaml` to unified artifact paths (tools, policy, toolsets, lockfile).

- `toolwright/core/toolpack.py` -> `resolve_toolpack()`
- Files: `toolpack.yaml`

### CAP-CROSS-002: Path Normalization & Aggregation

Normalize API paths, deduplicate endpoints, aggregate similar operations.

- `toolwright/core/normalize/path_normalizer.py` -> Path normalization
- `toolwright/core/normalize/aggregator.py` -> Endpoint aggregation

### CAP-CROSS-003: Flow Graph Detection

Detect API dependencies (action A enables/requires action B).

- `toolwright/core/normalize/flow_detector.py` -> Flow detection
- `toolwright/models/flow.py` -> Flow models

### CAP-CROSS-004: Endpoint Tagging

Auto-tag endpoints with resource type, operation type, risk keywords.

- `toolwright/core/normalize/tagger.py` -> Tagging logic

### CAP-CROSS-005: Interactive Terminal UI (TUI)

Rich terminal interface for approval review, repair flows, initialization, and status display.

- `toolwright/ui/console.py` -> Console utilities
- `toolwright/ui/prompts.py` -> Interactive prompts
- `toolwright/ui/flows/` -> Flow wizards (init, gate_review, repair, doctor, ship)
- `toolwright/ui/views/` -> Display components (branding, diff, next_steps, progress, status, tables)

### CAP-CROSS-006: Meta MCP Server (Introspection)

Governance-aware MCP server exposing Toolwright metadata as tools for agent self-service.

- `toolwright/mcp/meta_server.py` -> `ToolwrightMetaMCPServer`
- GOVERN tools: `toolwright_list_actions`, `toolwright_check_policy`, `toolwright_get_approval_status`, `toolwright_list_pending_approvals`, `toolwright_get_action_details`, `toolwright_risk_summary`, `toolwright_get_flows`
- HEAL tools: `toolwright_diagnose_tool`, `toolwright_health_check`
- KILL tools: `toolwright_kill_tool`, `toolwright_enable_tool`, `toolwright_quarantine_report`
- CORRECT tools: `toolwright_add_rule`, `toolwright_list_rules`, `toolwright_remove_rule`, `toolwright_suggest_rule`
- RECONCILE tools: `toolwright_reconcile_status`, `toolwright_pending_repairs`
- EXPAND tools: `toolwright_request_capability`
- CLI: `toolwright inspect --tools <path>`
- Params: `circuit_breaker_path`, `rules_path`, `state_dir` (optional, enable KILL/CORRECT/RECONCILE meta-tools)

### CAP-CROSS-007: Workflow Runner (Tide Integration)

Multi-step verification workflows with shell, HTTP, browser, and MCP steps.

- `toolwright/cli/commands_workflow.py` -> Workflow commands
- CLI: `toolwright workflow init|run|replay|diff|report|pack|export`

### CAP-CROSS-008: Docker/Container Runtime Emission

Generate container definitions for toolwright servers.

- `toolwright/core/runtime/container.py` -> Container emission

### CAP-CROSS-009: Status & Health Monitoring

Check project health, tool status, and dependency availability.

- `toolwright/ui/flows/doctor.py` -> Doctor flow
- CLI: `toolwright status`, `toolwright doctor`

### CAP-CROSS-010: Demo & Onboarding

Run interactive demo showcasing Toolwright capabilities.

- `toolwright/cli/demo.py` -> Demo command
- CLI: `toolwright demo`

### CAP-CROSS-011: Next.js Dynamic Path Resolution

Auto-resolve Next.js buildId from `__NEXT_DATA__` for dynamic API routes.

- `toolwright/mcp/server.py` -> `_resolve_nextjs_build_id()`

### CAP-CROSS-012: Diff & Change Detection

Compare current tools against approved baselines with structured output.

- `toolwright/ui/views/diff.py` -> Diff rendering
- CLI: `toolwright diff --toolpack <path> --format <json|github-md>`

### CAP-CROSS-014: OpenAPI Discovery

Probe API hosts for OpenAPI specs at well-known paths. Returns a CaptureSession for downstream compilation.

- `toolwright/core/discover/openapi.py` -> `OpenAPIDiscovery`
- Well-known paths: `/openapi.json`, `/openapi.yaml`, `/swagger.json`, `/v1/openapi.json`, `/api-docs`, `/.well-known/openapi.json`
- Methods: `async discover(host) -> CaptureSession | None`
- Delegates to `OpenAPIParser.parse_file()` on first successful response
- Handles: URL normalization, timeout, connection errors, invalid specs
- Tests: `tests/test_openapi_discovery.py`

### CAP-CROSS-015: Agent Capability Request

Meta-tool for agents to request new API capabilities. Creates PENDING proposals that require human approval (trust boundary: agents cannot self-approve).

- `toolwright/mcp/meta_server.py` -> `_request_capability()`, `toolwright_request_capability` tool definition
- Flow: agent provides host → OpenAPIDiscovery probes → CaptureSession → MissingCapability → ProposalEngine creates PENDING proposal
- Output: concise plain-text with proposal_id, endpoint count, and next-step guidance
- Proposals stored at: `<state_dir>/proposals/drafts/<proposal_id>.json`
- Tests: `tests/test_request_capability_meta.py`

### CAP-CROSS-016: Reconciliation Meta-Tools

Agent-facing meta-tools for reconciliation status and pending repairs. Return concise, agent-friendly text summaries under 200 tokens.

- `toolwright/mcp/meta_server.py` -> `_reconcile_status()`, `_pending_repairs()`
- `toolwright_reconcile_status`: per-tool health counts, non-healthy tool details, repair/approval counts
- `toolwright_pending_repairs`: patch listing with [kind] title — CLI command format, apply hint
- Optional filters: `filter_status` (for status), `filter_kind` (for repairs)
- Tests: `tests/test_reconcile_meta_tools.py`

### CAP-CROSS-013: Schema Version Migration

Migrate artifacts between schema versions.

- `toolwright/cli/migrate.py` -> Migration command
- CLI: `toolwright migrate`

---

## UX -- Toolpack Resolution & Naming

### CAP-UX-001: Toolpack Auto-Resolution

Automatic resolution of toolpack path when `--toolpack` is omitted. Resolution chain: explicit flag -> env var -> config file -> auto-detect single -> error with actionable message.

- `toolwright/utils/resolve.py` -> `resolve_toolpack_path()`
- Wired into: `commands_approval.py` (all gate commands), `commands_mcp.py` (serve), `main.py` (status, dashboard, diff, repair, verify, config, rename, run)
- Env var: `TOOLWRIGHT_TOOLPACK`
- Config: `.toolwright/config.yaml` -> `default_toolpack` (directory name)

### CAP-UX-002: Friendly Toolpack Naming

Human-friendly toolpack directory names derived from API hostnames instead of hash-based `tp_` prefixes. Collision handling via suffixes (`stripe`, `stripe-2`, `stripe-3`).

- `toolwright/utils/resolve.py` -> `generate_toolpack_slug()`, `_host_to_slug()`
- Used by: `toolwright/cli/mint.py`, `toolwright/cli/compile.py`
- Example: `api.stripe.com` -> directory `stripe`

### CAP-UX-003: Config File + `toolwright use`

Set/clear default toolpack for multi-toolpack projects. Config stored in `.toolwright/config.yaml`.

- `toolwright/utils/config_file.py` -> `load_config()`, `save_config()`
- `toolwright/cli/commands_use.py` -> `register_use_command()`
- CLI: `toolwright use <name>`, `toolwright use --clear`

### CAP-UX-004: Auth Check Diagnostic

Verify auth configuration for the active toolpack. Shows per-host and global env var status, probes endpoints by default.

- `toolwright/cli/commands_auth.py` -> `register_auth_check_command()`, `_host_to_env_var()`, `_probe_host()`
- CLI: `toolwright auth check [--no-probe]`
- Probes by default with `--no-probe` for offline/CI environments
