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
- `toolwright/core/auth/profiles.py` -> Auth profiles
- CLI: `toolwright auth`, `toolwright auth check`
- Auth display: shown in `mint` output after compile, with env var export suggestions

### CAP-CONNECT-012: Draft Toolpack Creation

Create draft toolpacks from discovered `CaptureSession` data (e.g., from OpenAPI discovery). Draft toolpacks are staged in `.toolwright/drafts/<id>/` for human review before promotion. Drafts are NOT loaded by `toolwright serve`.

- `toolwright/core/discover/draft_toolpack.py` -> `DraftToolpackCreator`
- Methods: `create(session, label)`, `list_drafts()`, `get_draft_path(draft_id)`
- Outputs: `toolpack.yaml` (with `draft: true`), `tools.json` (action manifest), `manifest.json` (metadata)
- Action generation: deduplicates by method+path, auto-names (e.g., `get_users`), assigns risk tiers
- Tests: `tests/test_draft_toolpack.py`

### CAP-CONNECT-013: One-Command Recipe-Based Creation (Create)

Instant toolpack from OpenAPI specs or bundled recipes (GitHub, etc.).

- `toolwright/cli/commands_create.py` -> `run_create()`
- CLI: `toolwright create <recipe-name>` or `toolwright create --spec <path>`

### CAP-CONNECT-006: One-Command API Onboarding (Mint)

Single command to capture API traffic via browser, compile tools, and publish a toolpack.

- `toolwright/cli/mint.py` -> `mint()`
- CLI: `toolwright mint <url> -a <api_domain>`

### CAP-CONNECT-007: MCP Server Provisioning

Start a governed MCP server on stdio transport serving compiled tools. Supports auth via env vars, per-host auth, and CLI flag. Toolpack path auto-resolves when omitted.

- `toolwright/mcp/server.py` -> `ToolwrightMCPServer`, `_resolve_auth_for_host()`
- `toolwright/mcp/runtime.py` -> `run_serve()`, auto-resolution via `resolve_toolpack_path()`
- CLI: `toolwright serve [--toolpack <path>] [--auth "Bearer <token>"] [--toolset <name>] [--max-risk <tier>] [--extra-header "Name: value"] [--schema-validation strict|warn|off]`
- Auth priority: `--auth` flag > `TOOLWRIGHT_AUTH_<NORMALIZED_HOST>` env var > `TOOLWRIGHT_AUTH_HEADER` env var > None
- Per-host env var naming: replace dots/hyphens with underscores, uppercase (e.g., `api.github.com` -> `TOOLWRIGHT_AUTH_API_GITHUB_COM`)
- `--toolset`: filter to named tool set (e.g., `readonly`)
- `--max-risk`: cap exposed tools by risk tier (`low`, `medium`, `high`, `critical`)
- `--extra-header` / `-H`: inject custom headers into every upstream request (e.g., `Notion-Version: 2025-09-03`). Can be specified multiple times. Does not override Authorization.
- `--schema-validation`: control outputSchema advertisement. `strict` advertises schemas, `warn` (default) and `off` suppress them.
- Auth warning: prints `WARNING` at startup when expected per-host auth env vars are not set

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

- Cloud metadata endpoints (169.254.169.254, fd00::) are unconditionally blocked; no flag overrides this.
- Private CIDR and redirects are blocked by default; `--allow-private-cidr` and `--allow-redirects` opt in.
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

### CAP-GOVERN-010: Confirmation Gate (Out-of-Band)

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

### CAP-HEAL-012: Variant-Aware Baseline Store

Ring buffer storage, freeze/unfreeze, atomic writes for heal baselines.

- `toolwright/core/heal/baseline_store.py` -> `BaselineStore`, `VariantStore`

### CAP-HEAL-013: Confidence-Aware Schema Inference

Schema inference with tiered optionality. JSON body to typed shape conversion. ResponseSample factory from probe results.

- `toolwright/core/heal/schema_inference.py` -> schema inference with tiered optionality
- `toolwright/core/heal/typed_shape.py` -> JSON body to typed shape conversion
- `toolwright/core/heal/sample_factory.py` -> ResponseSample factory from probe results

### CAP-HEAL-014: Shape Probe Loop

Schedule-aware shape-based drift probing in `serve --watch` mode.

- `toolwright/core/drift/shape_probe_loop.py` -> `ShapeProbeLoop`

### CAP-HEAL-015: Drift Action Handler

Severity-to-action mapping: SAFE auto-merge, APPROVAL_REQUIRED/MANUAL escalation.

- `toolwright/core/drift/drift_handler.py` -> `DriftAction`, `handle_drift()`

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

### CAP-CORRECT-010: Rule Templates

Bundled reusable rule templates (crud-safety, rate-control, retry-safety) that create DRAFT behavioral rules. Templates use glob-based targeting (`target_name_patterns`) for overlay-forward compatibility.

- `toolwright/rules/templates/*.yaml` -> Template definitions
- `toolwright/rules/loader.py` -> `list_templates()`, `load_template()`, `apply_template()`
- `toolwright/cli/commands_rules.py` -> `rules template list|show|apply`
- CLI: `toolwright rules template list`, `toolwright rules template apply crud-safety`

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
- Note: capability proposals use PENDING status (distinct from DRAFT status used by behavioral rules in CAP-CORRECT-009). Both require human activation before taking effect.

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

### CAP-UX-005: Smart Pre-Flight Probe (Mint)

Before every `mint` command (opt-out via `--no-probe`), probe each allowed host for auth requirements (401/403 + WWW-Authenticate parsing), Content-Type (JSON vs HTML portal), OpenAPI specs at well-known paths, and GraphQL introspection. Outputs structured results with exact `export` commands for auth setup.

- `toolwright/cli/mint.py` -> `_probe_hosts()`, `_probe_base_url()`, `_probe_openapi()`, `_probe_graphql()`
- `toolwright/cli/mint.py` -> `_render_probe_results()` (✓/⚠/✗/○ icons)
- `toolwright/core/drift/probe_executor.py` -> `ProbeExecutor`
- `toolwright/core/drift/probe_template.py` -> `extract_probe_template()`
- `toolwright/models/probe_template.py` -> `ProbeTemplate`

### CAP-UX-006: Auth Startup Warning

At `toolwright serve` startup, warn when expected per-host auth env vars (`TOOLWRIGHT_AUTH_<HOST>`) are not set. Prints actionable `export` command with correct env var name and `"Bearer <token>"` format.

- `toolwright/cli/mcp.py` -> `warn_missing_auth()`
- Env var pattern: `TOOLWRIGHT_AUTH_` + uppercased host with non-alnum replaced by `_`

### CAP-UX-007: Empty Toolpack Guard

Block `toolwright serve` when the toolpack contains 0 tools. Prints actionable error directing the user to run `toolwright mint`.

- `toolwright/cli/mcp.py` -> `run_mcp_serve()` (0-actions check before auth warnings)

### CAP-UX-008: API Recipes

Bundled API recipes (github, stripe) that pre-fill mint settings — hosts, auth headers, extra headers, rule template references, and probe hints. Recipes reduce setup friction, not governance decisions. Only recipes with working OpenAPI spec URLs are shipped.

- `toolwright/recipes/*.yaml` -> Recipe definitions
- `toolwright/recipes/loader.py` -> `list_recipes()`, `load_recipe()`
- `toolwright/cli/commands_recipes.py` -> `recipes list|show`
- `toolwright/cli/main.py` -> `mint --recipe <name>`
- CLI: `toolwright recipes list`, `toolwright recipes show github`, `toolwright mint --recipe github`

### CAP-UX-009: Guided Ship Lifecycle

End-to-end guided workflow: capture -> review -> approve -> snapshot -> verify -> serve.

- `toolwright/cli/commands_onboarding.py` -> `ship` command
- `toolwright/ui/flows/ship.py` -> `ship_flow()`

### CAP-UX-010: Terminal TUI Dashboard

Full-screen read-only Textual dashboard (distinct from web dashboard in CAP-CROSS-021).

- `toolwright/ui/dashboard/app.py` -> Textual-based TUI
- `toolwright/cli/commands_status.py` -> `dashboard` command

---

## SERVE -- HTTP Transport & Dashboard

### CAP-CROSS-017: Request Pipeline Abstraction

Extracted tool-call lifecycle as a reusable pipeline that both stdio and HTTP transports invoke.

- `toolwright/mcp/pipeline.py` -> `RequestPipeline`, `PipelineContext`, `PipelineResult`
- Stages: action lookup, decision engine, confirmation gate, rule check, breaker check, dry-run, HTTP execution, response processing
- Wired into: `toolwright/mcp/server.py` -> `handle_call_tool` delegates to pipeline

### CAP-CROSS-018: HTTP Transport (StreamableHTTP)

MCP server over HTTP with Starlette + StreamableHTTPSessionManager. Default port 8745.

- `toolwright/mcp/http_transport.py` -> `ToolwrightHTTPApp`
- Routes: `/health`, `/mcp`, `/api/*`, `/` (static dashboard)
- CLI: `toolwright serve --http [--host HOST] [--port PORT]`

### CAP-CROSS-019: Token Authentication

Bearer token auth for HTTP transport. Auto-generated in TTY, env var in non-TTY.

- `toolwright/mcp/auth.py` -> `generate_token()`, `validate_token()`, `mask_token()`, `TokenAuthMiddleware`
- Token format: `tw_` + 32 hex chars
- ENV: `TOOLWRIGHT_TOKEN`
- Exempt: `/health`

### CAP-CROSS-020: EventBus (In-Memory Event Stream)

Bounded ring buffer for server events with synchronous publish and async subscribe.

- `toolwright/mcp/events.py` -> `EventBus`, `ServerEvent`
- Max 1000 events, drop-oldest on overflow
- Event types: `tool_called`, `decision`, `drift_detected`, `auto_repaired`, `breaker_tripped`, `breaker_recovered`, `quarantined`, `repair_queued`, `repair_failed`, `probe_result`

### CAP-CROSS-021: Web Dashboard (Static SPA)

Single-page dark-themed dashboard showing tools, events, reconciliation status.

- `toolwright/assets/dashboard/index.html` -> Dashboard HTML
- `toolwright/assets/dashboard/style.css` -> Dark theme styles
- `toolwright/assets/dashboard/app.js` -> SSE consumer, API fetchers, DOM rendering
- Auth: token-in-URL → memory → strip via replaceState
- Budget: <50KB total, no framework, no build step

### CAP-CROSS-022: Dashboard JSON API

REST endpoints for dashboard data, served alongside MCP.

- `toolwright/mcp/http_transport.py` -> API route handlers
- `GET /api/overview` -> Toolpack metadata, health summary
- `GET /api/tools` -> Tool list with risk, status, breaker state
- `GET /api/events` -> Recent events (paginated)
- `GET /api/events/stream` -> SSE live feed from EventBus

### CAP-CROSS-023: Description Optimizer

Reduce tool descriptions to ~80-120 tokens for context efficiency. `--verbose-tools` restores originals.

- `toolwright/mcp/description.py` -> `optimize_description()`
- CLI: `toolwright serve --verbose-tools`

### CAP-CROSS-024: Tool Filtering

Filter served tools by glob pattern and max risk ceiling.

- CLI: `toolwright serve --tools "get_*" --max-risk medium`

### CAP-CROSS-030: Rich Startup Card

Formatted startup banner showing tool count, risk breakdown, context budget, URLs. Shows scope info and total compiled count when `--scope` is active.

- `toolwright/mcp/startup_card.py` -> `render_startup_card(scope_info=, total_compiled=)`

### CAP-CROSS-031: Auto-Generated Tool Groups

Automatically group tools by URL resource path during compilation. Groups are generated from the first semantic URL segment (after stripping noise like `api`, `admin`, version prefixes, path params). Large groups (>80 tools) are recursively split by secondary segments up to depth 3.

- `toolwright/models/groups.py` -> `ToolGroup`, `ToolGroupIndex`
- `toolwright/core/compile/grouper.py` -> `generate_tool_groups()`, `extract_semantic_segments()`
- Output: `groups.json` alongside `tools.json`
- Integrated into: `toolwright compile` and `toolwright mint`

### CAP-CROSS-032: Serve-Time Scope Filtering

Filter served tools to specific groups via `--scope`. Accepts comma-separated group names with prefix matching (`repos` matches `repos`, `repos/issues`, `repos/pulls`). Unknown names trigger fuzzy suggestions (Levenshtein distance <= 2).

- `toolwright/core/compile/grouper.py` -> `filter_by_scope()`, `suggest_group_name()`
- CLI: `toolwright serve --scope products,orders`

### CAP-CROSS-033: Tool Count Guardrails

Warn when serving 31-200 tools; block above 200 unless `--no-tool-limit` overrides. Warnings include group suggestions when groups.json is available.

- `toolwright/cli/mcp.py` -> `check_tool_count_guardrails()`
- Constants: `TOOL_COUNT_WARN_THRESHOLD = 30`, `TOOL_COUNT_BLOCK_THRESHOLD = 200`
- CLI: `toolwright serve --no-tool-limit`

### CAP-CROSS-034: Groups CLI Commands

List and inspect auto-generated tool groups from a toolpack.

- `toolwright/cli/commands_groups.py` -> `register_groups_commands()`
- CLI: `toolwright groups list [--toolpack ...]`, `toolwright groups show <name> [--toolpack ...]`

### CAP-CROSS-035: Gate Status by Group

Show per-group approval summary in the gate status command.

- `toolwright/cli/commands_approval.py` -> `gate_status(by_group=True)`
- CLI: `toolwright gate status --by-group [--toolpack ...]`

---

## GOVERN -- Smart Defaults & Client Integration

### CAP-CROSS-025: Smart Gate Defaults

Risk-based auto-approval during ship flow. Low/medium auto-approved, high prompted (default Yes), critical prompted (default No).

- `toolwright/core/approval/smart_gate.py` -> `classify_approval()`, `ApprovalClassification`
- Provenance: `approved_by: risk_policy:low|medium` vs `approved_by: human:interactive`

### CAP-CROSS-026: MCP Client Config Auto-Install

Detect and configure Claude Desktop and Cursor MCP client configs.

- `toolwright/utils/mcp_clients.py` -> `detect_mcp_clients()`, `install_config()`, `uninstall_config()`
- Platforms: macOS, Linux, Windows
- Safety: `.bak` backup before modify, refuse on JSON parse error

---

## SHARE -- Toolpack Distribution

### CAP-CROSS-028: Toolpack Sharing (.twp Bundles)

Package toolpacks into signed .twp bundles (gzipped tar) for distribution.

- `toolwright/core/share/bundler.py` -> `create_bundle()`
- `toolwright/core/share/installer.py` -> `install_bundle()`, `InstallResult`
- Contents: manifest.json, signature.json, toolpack.yaml, artifacts
- Signature: SHA256 content hash with self-signed verification
- Excludes: private keys, auth tokens, state files

---

## CONSOLE -- Real-Time Agent Operations Console

### CAP-CONSOLE-001: WorkItem Model

Unified data model for actionable items requiring human attention. Six kinds with deterministic IDs for dedup across reconnects/restarts.

- `toolwright/models/work_item.py` -> `WorkItem`, `WorkItemKind`, `WorkItemStatus`, `WorkItemAction`
- Kinds: TOOL_APPROVAL, CONFIRMATION, REPAIR_PATCH, CIRCUIT_BREAKER, RULE_DRAFT, CAPABILITY_REQUEST
- Statuses: OPEN → APPROVED / DENIED / APPLIED / DISMISSED / EXPIRED
- Deterministic IDs: `wi_approval_{tool_id}`, `wi_confirm_{token_id}`, etc.
- Tests: `tests/test_work_item.py`

### CAP-CONSOLE-002: WorkItem Factory Functions

Type-safe factory functions producing WorkItems with deterministic IDs, evidence payloads, and pre-configured action buttons.

- `toolwright/core/work_items.py` -> `create_tool_approval_item()`, `create_confirmation_item()`, `create_circuit_breaker_item()`, `create_repair_patch_item()`, `create_rule_draft_item()`, `create_capability_request_item()`
- Tests: `tests/test_work_item.py` (factory tests)

### CAP-CONSOLE-003: EventStore (Persistent Event Stream)

Persistent event store with ring buffer, per-item JSON file persistence, audit JSONL log, and SSE subscription queues. Crash-safe via atomic writes (tmp + os.replace).

- `toolwright/mcp/event_store.py` -> `EventStore`, `ConsoleEvent`
- Ring buffer: 5000 max events, monotonic IDs
- Persistence: `.toolwright/state/console/items/<id>.json`
- Audit: `.toolwright/state/console/audit.jsonl`
- Methods: `publish_event()`, `publish_work_item()` (upsert), `resolve_work_item()` (async with lock), `check_expirations()`, `events_since()`, `subscribe()`/`unsubscribe()`
- Tests: `tests/test_event_store.py`

### CAP-CONSOLE-004: Action Handlers (Control Plane API)

POST endpoints following "side effect BEFORE resolution" pattern. Each handler: lookup → idempotent check → conflict check → side effect → resolve → publish event.

- `toolwright/mcp/action_handlers.py` -> `ActionContext`, `set_context()`, all `handle_*` functions
- Gate: `handle_gate_allow` (bulk), `handle_gate_block`
- Confirm: `handle_confirm_grant`, `handle_confirm_deny`
- Breaker: `handle_kill_tool`, `handle_enable_tool`
- Rules: `handle_rule_activate`, `handle_rule_dismiss`
- Repair: `handle_repair_apply`, `handle_repair_dismiss`
- GET: `handle_list_work_items`, `handle_get_work_item`, `handle_status_counts`
- Tests: `tests/test_action_handlers.py`

### CAP-CONSOLE-005: Console SSE Stream

Resumable SSE stream with Last-Event-ID support, full-state sync on connect, and status counter updates.

- `toolwright/mcp/http_transport.py` -> `handle_console_stream`, `_format_sse_event()`, `_format_sse_sync()`, `_format_sse_status()`
- Route: `GET /api/stream`
- Event types: `message` (with optional work_item), `sync` (full state replace), `status` (counters)
- Headers: `X-Accel-Buffering: no`, `Referrer-Policy: no-referrer`

### CAP-CONSOLE-006: Action Routes

POST routes for control plane actions, gated by token auth.

- `toolwright/mcp/http_transport.py` -> Action route registration
- Routes:
  - `POST /api/act/gate/allow` (bulk tool approval)
  - `POST /api/act/gate/block` (tool rejection)
  - `POST /api/act/confirm/grant`, `/api/act/confirm/deny`
  - `POST /api/act/kill`, `/api/act/enable`
  - `POST /api/act/rule/activate`, `/api/act/rule/dismiss`
  - `POST /api/act/repair/apply`, `/api/act/repair/dismiss`
- GET routes: `/api/work-items`, `/api/work-items/{item_id}`, `/api/status`

### CAP-CONSOLE-007: Expiration Loop

Background asyncio.Task that checks for expired work items (e.g., confirmations with TTL) and calls `confirmation_store.deny()` to unblock frozen agents.

- `toolwright/mcp/http_transport.py` -> `_run_expiration_loop()`
- Interval: 5 seconds
- Side effect: denies expired confirmations before marking EXPIRED

### CAP-CONSOLE-008: Console Frontend (Single-File SPA)

Dark-themed, vanilla JS console frontend served as static HTML. Terminal aesthetic, no framework, no build step.

- `toolwright/assets/console/index.html` -> Complete console UI (<25KB)
- Features: status bar (open/blocking/events/uptime), filter bar (6 kinds), event feed, work item cards with action buttons, bulk approval bar, blocking timer, new events pill
- SSE auto-reconnect with exponential backoff
- Safe DOM methods (createElement, textContent) — no innerHTML
- Auth: token-in-URL → memory → strip via replaceState

### CAP-CONSOLE-009: Pipeline Console Integration

RequestPipeline emits console events for tool calls, confirmations, and failures.

- `toolwright/mcp/pipeline.py` -> `_emit_console_event()`, console event publishing in `_handle_confirm()` and `_execute_and_process()`
- Event types: `confirmation_requested`, `tool_call_success`, `tool_call_failed`
- Creates CONFIRMATION WorkItems for blocking confirmation requests

### CAP-CONSOLE-010: Startup WorkItem Generation

At HTTP server startup, creates TOOL_APPROVAL WorkItems for all pending (unapproved) tools in the lockfile.

- `toolwright/mcp/server.py` -> `_create_startup_work_items()`
- Emits `tool_pending` console events for each unapproved tool

---

## OBSERVE -- Telemetry

### CAP-CROSS-029: Observability (Tracing & Metrics)

No-op tracer (OTEL-compatible) and hand-rolled Prometheus metrics registry.

- `toolwright/mcp/observe.py` -> `create_tracer()`, `MetricsRegistry`
- Tracer: no-op fallback when opentelemetry not installed
- Metrics: counters, gauges, histograms with Prometheus text exposition
- No external deps required; optional OTEL/prometheus-client for production

### CAP-CROSS-036: Response Baseline Inference for Traffic-Captured Tools

Automatically infer structural JSON schemas from captured HTTP responses. Store as canonical shape model with presence statistics. Zero configuration required.

- `toolwright/models/shape.py` -> `ShapeModel`, `FieldShape`
- `toolwright/core/drift/shape_inference.py` -> `infer_shape()`, `merge_observation()`, `InferenceMetadata`
- Shape model uses flat JSON pointer paths (e.g., `.products[].id`)
- Per-field presence tracking: `seen_count` / `sample_count` -> `presence_ratio`
- Array presence is per-sample (100-item array = 1 observation, not 100)
- Empty/truncated array metadata prevents false dilution of presence stats

### CAP-CROSS-037: Probe Templates for Drift Detection

Store sanitized request templates per tool at compile time. Reproduce query params, headers, and API version for accurate probing. Strip ephemeral tokens, pagination cursors, and auth credentials.

- `toolwright/models/probe_template.py` -> `ProbeTemplate`
- `toolwright/core/drift/probe_template.py` -> `extract_probe_template()`, param/header sanitization
- STRIP_PARAMS: pagination cursors, auth tokens, cache busters, request IDs
- KEEP_PARAMS: field selection, filters, sort, pagination size, API version
- STRIP_HEADERS: Authorization, Cookie, x-api-key, auth-pattern X-* headers
- Value heuristics: JWTs and long base64 tokens stripped regardless of header name

### CAP-CROSS-038: Structural Drift Detection for Traffic-Captured GET Endpoints

Probe endpoints using stored request template. Diff response shape against baseline with severity classification: SAFE (new fields), APPROVAL_REQUIRED (nullability changes), MANUAL (required field removed).

- `toolwright/core/drift/shape_diff.py` -> `diff_shapes()`, `overall_severity()`
- `toolwright/core/drift/shape_diff.py` -> `DriftChange`, `DriftChangeType`, `DriftSeverity`
- 10 change types: FIELD_ADDED, TYPE_WIDENED_SAFE, NULLABILITY_CHANGED, ARRAY_ITEM_TYPE_CHANGED, OPTIONAL_KEY_REMOVED, REQUIRED_PATH_MISSING, TYPE_NARROWED, TYPE_CHANGED_BREAKING, ROOT_TYPE_CHANGED, OPTIONAL_PATH_ADDED
- Empty/truncated array awareness: descendants are "unknown," not "missing"
- Decide-first-merge-later: baseline is never mutated during classification

### CAP-CROSS-039: Effectively-Required Field Detection

Track per-field presence statistics across observations. Fields present in >= 95% of samples are "effectively required." Missing effectively-required fields classify as MANUAL (breaking).

- `toolwright/models/shape.py` -> `FieldShape.is_effectively_required()`
- `toolwright/core/drift/constants.py` -> `EFFECTIVELY_REQUIRED_THRESHOLD` (0.95), `MIN_SAMPLES_FOR_PRESENCE` (3)
- Low sample counts (< MIN_SAMPLES) always classify as APPROVAL_REQUIRED, never MANUAL
- Prevents false alarms from single-sample baselines

### CAP-CROSS-040: Decide-First-Merge-Later Drift Resolution

Drift is classified before any baseline mutation. SAFE changes auto-merge; others require approval. Baseline integrity preserved until explicit action.

- `toolwright/core/drift/shape_diff.py` -> `diff_shapes()` does NOT mutate models
- `toolwright/core/drift/shape_inference.py` -> `merge_observation()` is the single merge function
- All merges (compile-time, SAFE drift, approved drift) go through `merge_observation()`
- `toolwright/models/baseline.py` -> `BaselineIndex`, `ToolBaseline` with atomic save + threading lock
- `toolwright/core/toolpack.py` -> `ToolpackPaths.baselines`, `ResolvedToolpackPaths.baselines_path`

### CAP-CROSS-041: Plan Report Engine

Generate structured plan reports from toolpack analysis.

- `toolwright/core/plan/engine.py` -> plan report generation
- `toolwright/models/plan.py` -> plan models
- `toolwright/cli/plan.py` -> CLI command

---

## OVERLAY — Govern any existing MCP server

### CAP-OVERLAY-001: Wrap CLI Command

`toolwright wrap` connects to any existing MCP server (stdio or Streamable HTTP) and exposes a governed proxy. Supports auto-derived server names, saved configs, and header passthrough.

- `toolwright/cli/commands_wrap.py` -> `wrap_command()` Click command
- `toolwright/cli/main.py` -> registered in `ADVANCED_COMMANDS` (visible via `--help-all`)
- Subcommands: `--url` (HTTP target), `--auto-approve` (low-risk), `--dry-run`, `--rules`, `--circuit-breaker`

### CAP-OVERLAY-002: Upstream Connection (stdio + HTTP)

Unified connection interface for upstream MCP servers. Supports stdio (subprocess) and Streamable HTTP targets. Uses `AsyncExitStack` for lifetime management and `Semaphore(10)` for concurrency.

- `toolwright/overlay/connection.py` -> `WrappedConnection`
- Methods: `connect()`, `list_tools()`, `call_tool()`, `reconnect()`, `close()`
- Delegates to MCP SDK's `stdio_client` and `streamablehttp_client`

### CAP-OVERLAY-003: Tool Discovery + Risk Classification

Enumerates upstream tools, classifies risk tiers using name heuristics + MCP annotations, and computes digest-based signatures for change detection.

- `toolwright/overlay/discovery.py` -> `discover_tools()`, `classify_risk()`, `tool_def_digest()`
- Critical: delete/remove/destroy/drop/purge/revoke patterns
- High: create/update/modify/write/send/push/execute/run (default)
- Low: only when BOTH heuristics AND annotations agree (readOnlyHint)
- `compute_tool_def_digest()` -> SHA256(name+desc+schema+annotations)[:16]

### CAP-OVERLAY-004: Synthetic Manifest Generation

Converts DiscoveryResult into a tools.json-compatible manifest with synthetic `method="MCP"`, `path="mcp://<server>/<tool>"`, `host="<server_name>"` values.

- `toolwright/overlay/discovery.py` -> `build_synthetic_manifest()`
- Enables reuse of existing lockfile, pipeline, and decision engine infrastructure

### CAP-OVERLAY-005: MCP Result Normalizer

Converts MCP `CallToolResult` (content blocks + isError) into the pipeline envelope format `{status_code, data, action}`. Handles text, JSON, multi-content, non-text (graceful degradation), and errors.

- `toolwright/overlay/normalizer.py` -> `normalize_mcp_result()`
- Single text block: attempts JSON parse; multiple blocks: concatenates with newlines
- Non-text content: placeholder string `[<type> content]`

### CAP-OVERLAY-006: Overlay Server (Governance Proxy)

Composition-based MCP proxy that wires RequestPipeline, DecisionEngine, and all governance pillars (CORRECT, KILL) with the overlay executor. Does NOT subclass ToolwrightMCPServer.

- `toolwright/overlay/server.py` -> `OverlayServer`
- `_proxy_call()` -> upstream call + normalize
- `_register_handlers()` -> MCP list_tools/call_tool handlers
- `_format_mcp_result()` -> PipelineResult to MCP wire format
- `run_stdio()` -> stdio transport
- `sync_lockfile()` -> approval tracking via LockfileManager

### CAP-OVERLAY-007: Per-Server Lockfile + Approval Flow

Each wrapped server gets its own lockfile at `.toolwright/wrap/<name>/lockfile.yaml`. New tools are PENDING; changed digests trigger re-approval; auto-approve low-risk when `--auto-approve` flag is set.

- `toolwright/models/overlay.py` -> `WrapConfig.lockfile_path` property
- `toolwright/overlay/server.py` -> `sync_lockfile()` delegates to `LockfileManager.sync_from_manifest()`
- `signature_id = tool_def_digest` enables existing change detection

### CAP-OVERLAY-008: Config Persistence + Name Derivation

Saves/loads wrap config as YAML at `.toolwright/wrap/<name>/wrap.yaml`. Server names auto-derived from command patterns, stripping `server-` and `mcp-server-` prefixes.

- `toolwright/overlay/config.py` -> `derive_server_name()`, `save_wrap_config()`, `load_wrap_config()`
- `build_client_config()` -> generates Claude Desktop + Claude Code config blocks

### CAP-OVERLAY-009: Lifecycle Management

Crash detection + exponential backoff restart for stdio targets. Health monitoring via `list_tools()` probe for HTTP targets.

- `toolwright/overlay/lifecycle.py` -> `StdioLifecycleManager`, `HttpHealthMonitor`

### CAP-OVERLAY-010: Source Locator

Finds editable source code for wrapped MCP servers (vendored > .py script > .js script).

- `toolwright/overlay/source_locator.py` -> `SourceLocator.locate()`

### CAP-OVERLAY-011: Overlay Data Models

Pydantic models for overlay mode: target types, config, wrapped tools, discovery results.

- `toolwright/models/overlay.py` -> `TargetType`, `WrapConfig`, `WrappedTool`, `SourceInfo`, `DiscoveryResult`
- `compute_tool_def_digest()` -> deterministic signature for change detection

