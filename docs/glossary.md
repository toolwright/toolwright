# Glossary

Key terms used throughout Toolwright documentation.

## Core Concepts

**Toolwright**
Agent tool supply chain governance system. Captures real API traffic, compiles governed tool definitions, and serves them through MCP with lockfile-based approval and fail-closed enforcement.

**MCP (Model Context Protocol)**
Standard protocol for AI agents to discover and use tools. Toolwright generates MCP-compatible tool definitions and serves them through an MCP server.

**Toolpack**
A compiled, versioned bundle of tool definitions, policy configuration, and metadata. Produced by `toolwright compile` or `toolwright mint`. Contains `toolpack.yaml`, `tools.json`, `policy.yaml`, and associated artifacts.

**Lockfile** (`toolwright.lock.yaml`)
Signed record of approved tools, similar to `package-lock.json` or `Cargo.lock`. Each entry includes the tool name, schema digest, approval decision (allow/block), and an Ed25519 signature. No lockfile = no runtime.

**Tool Surface**
The set of API endpoints exposed as agent-callable tools. Changes to the tool surface are detected by `toolwright drift`.

**Governance Loop**
The full lifecycle: capture -> compile -> review -> approve -> serve -> verify. Each stage produces auditable artifacts.

## Capture

**HAR (HTTP Archive)**
Standard format for recorded HTTP traffic. Toolwright imports HAR files to discover API endpoints.

**OpenTelemetry (OTEL)**
Observability framework. Toolwright imports OTEL trace files as an alternative to HAR for endpoint discovery.

**OpenAPI Spec**
API specification format (YAML/JSON). Toolwright auto-detects and imports OpenAPI specs to generate tool definitions without live traffic.

**Endpoint**
A discovered API operation (method + path + host). Endpoints are the raw material that gets compiled into tools.

## Compilation

**Scope**
Permission boundary defining what a tool is allowed to do. Scopes classify endpoints as read, write, delete, etc. and assign risk tiers.

**Risk Tier**
Classification of an endpoint's risk level: `low`, `medium`, `high`, or `critical`. Determined by HTTP method, path keywords, auth sensitivity, and PII presence.

**Patch Safety**
Classification of how a repair can be applied: `SAFE` (auto-apply without review), `APPROVAL_REQUIRED` (needs human approval), or `MANUAL` (requires investigation). Not to be confused with risk tiers (low/medium/high/critical), which classify tools. The `--auto-heal safe` flag means "auto-apply patches classified as SAFE," not "auto-heal low-risk tools."

**Redaction**
Automatic removal of sensitive data (cookies, tokens, API keys, PII) from captured traffic and evidence bundles. Enabled by default.

**Redaction Profile**
Named configuration controlling what gets redacted. `default_safe` handles auth headers and tokens. `high_risk_pii` adds email, phone, and SSN detection.

## Approval

**Gate**
The approval workflow. `toolwright gate allow` approves tools. `toolwright gate block` blocks them. `toolwright gate check` validates all tools are approved (for CI).

**Signature**
Ed25519 digital signature on each lockfile entry. Proves who approved what and when. Verification fails if signatures don't match.

**Fail-Closed**
Default enforcement mode. If a tool is not explicitly approved in the lockfile, it cannot execute. No lockfile = no runtime. No exceptions.

**Runtime Confirmation**
Out-of-band human confirmation for sensitive tool calls at runtime. When a policy
rule requires `confirm`, the MCP server pauses and issues a single-use token. The
operator grants via `toolwright confirm grant <token>`. Distinct from gate approval
(compile-time lockfile signing via `toolwright gate allow`).

## Runtime

**Drift**
Detected changes between the current API behavior and approved tool definitions. `toolwright drift` compares a baseline snapshot against the current state and reports additions, removals, and schema changes.

**Reconciliation**
Continuous background process that monitors tools for drift, schema changes, and endpoint failures on a risk-tier schedule. Started with `toolwright serve --watch`. Detected issues are classified by patch safety and either auto-applied or queued for review depending on the `--auto-heal` level.

**Circuit Breaker**
Per-tool state machine that isolates failing tools. Three states: CLOSED (normal), OPEN (blocked after repeated failures), HALF_OPEN (probing for recovery). Automatic breakers trip after 5 consecutive failures and recover after 60 seconds. Manual kills via `toolwright kill` never auto-recover.

**Snapshot**
Point-in-time copy of the toolpack state, created automatically before each auto-repair. Used for rollback if a repair causes problems. Managed with `toolwright snapshots` and `toolwright rollback`.

**EventBus**
In-memory ring buffer that distributes server events (tool calls, decisions, drift, breaker state changes) to subscribers. Publish is synchronous (never blocks the tool call path); subscribe is async (SSE consumers await new events). Bounded to ~1000 events; oldest are dropped when full.

**Evidence Bundle**
Redacted artifacts from a verification or governance run, including SHA-256 digests for integrity. Used for audit trails and CI gates.

**DecisionTrace**
Audit log entry recording a governance decision (tool allowed, blocked, or drift detected) with timestamp, context, and rationale.

## Proposals

**Proposal**
An agent-initiated request for a new capability or behavioral rule. Proposals are always created in draft state and require human approval before taking effect. Agents cannot approve their own proposals. See `toolwright propose`, `toolwright rules drafts`.

## Verification

**Contract**
Assertion-based verification rule. Contracts define expected behavior (e.g., "this tool must have a lockfile entry", "no critical-risk tools without explicit approval"). Run with `toolwright verify`.

**Replay Parity**
Property that two independent compilation runs from the same inputs produce identical artifacts and digests. Proved by `toolwright demo`.

## Workflow

**Demo / Prove Smoke**
Toolwright-native proof flows exposed by `toolwright demo` and `toolwright demo --smoke`. They generate governed demo toolpacks and write the release-readiness proof artifacts:

- `prove_twice_report.md`
- `prove_twice_diff.json`
- `prove_summary.json`
