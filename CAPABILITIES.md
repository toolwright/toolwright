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

Automatically detect and extract auth patterns (Bearer, OAuth, API keys) from captured traffic.

- `toolwright/core/auth/detector.py` -> `AuthDetector`
- `toolwright/core/auth/provider.py` -> `AuthProvider`
- `toolwright/core/auth/profiles.py` -> Auth profiles
- CLI: `toolwright auth`

### CAP-CONNECT-006: One-Command API Onboarding (Mint)

Single command to capture API traffic via browser, compile tools, and publish a toolpack.

- `toolwright/cli/mint.py` -> `mint()`
- CLI: `toolwright mint <url> -a <api_domain>`

### CAP-CONNECT-007: MCP Server Provisioning

Start a governed MCP server on stdio transport serving compiled tools.

- `toolwright/mcp/server.py` -> `ToolwrightMCPServer`
- `toolwright/cli/mcp.py` -> `run_mcp_serve()`
- CLI: `toolwright serve --toolpack <path>`

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

Review, approve, block, or conditionally approve tools before use.

- `toolwright/cli/approve.py` -> Approval logic
- `toolwright/cli/commands_approval.py` -> Gate command group
- `toolwright/ui/flows/gate_review.py` -> Interactive approval flow
- CLI:
  - `toolwright gate sync` -- Sync lockfile with manifest
  - `toolwright gate status` -- List approval states
  - `toolwright gate allow` -- Approve tools
  - `toolwright gate block` -- Block tools
  - `toolwright gate check` -- CI gate (exit 0 if all approved)

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

Block excessively large responses to prevent memory exhaustion.

- `toolwright/models/decision.py` -> `ReasonCode.denied_response_too_large`
- ENV: `TOOLWRIGHT_MAX_RESPONSE_BYTES`

### CAP-KILL-005: Path Blocklist

Block known non-API paths (static assets, health checks, etc.) from tool discovery.

- `toolwright/core/capture/path_blocklist.py` -> Path blocklist patterns

---

## CORRECT -- Compile-Time Policy Rules

### CAP-CORRECT-001: Compile-Time Policy Rules

Define static access control rules (allow/deny/confirm/budget/audit/redact) that are compiled into `policy.yaml`.

- `toolwright/core/compile/policy.py` -> Policy generation
- `toolwright/models/policy.py` -> Policy models
- Files: `policy.yaml`

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
- Tools: `toolwright_list_actions`, `toolwright_check_policy`, `toolwright_get_approval_status`, `toolwright_list_pending_approvals`, `toolwright_get_action_details`, `toolwright_risk_summary`, `toolwright_get_flows`
- CLI: `toolwright inspect --tools <path>`

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

### CAP-CROSS-013: Schema Version Migration

Migrate artifacts between schema versions.

- `toolwright/cli/migrate.py` -> Migration command
- CLI: `toolwright migrate`
