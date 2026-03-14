# TODOS

> Deferred work items from CEO reviews and plan sessions. Each item includes context so anyone picking it up understands the motivation.

---

## ~~Auth UX Overhaul~~ (COMPLETED 2026-03-14)

All 5 items shipped. Files: `toolwright/utils/dotenv.py`, `toolwright/utils/auth.py`, `toolwright/cli/auth_setup.py`, `toolwright/mcp/runtime.py` (auto-prompt), recipes updated with `auth_guide`. Tests: `tests/test_dotenv.py`, `tests/test_auth_setup.py`, `tests/test_auth_serve_prompt.py`, `tests/test_auth_utils.py`.

---

## Transport-Agnostic Governance (from CEO Strategic Review 2026-03-13)

**Context**: CEO review determined that toolwright's governance engine is already transport-agnostic in design but MCP-coupled in implementation. The market is splitting into CLI-first (10-32x cheaper, 100% reliable) and MCP-first (enterprise compliance, multi-tenant auth) camps. Rather than picking a side, toolwright should govern both. The `ToolwrightMCPServer` monolith (1000+ lines) tangles governance, execution, and MCP transport — extraction unlocks multi-transport support with minimal new code.

### ~~TODO-TRANSPORT-001: Extract GovernanceEngine from ToolwrightMCPServer~~ (COMPLETED 2026-03-14)

Shipped as GovernanceRuntime (`toolwright/core/governance/runtime.py`) + GovernanceEngine (`toolwright/core/governance/engine.py`). ToolwrightMCPServer refactored to delegate to GovernanceRuntime. `transport_type` parameterized in DecisionRequest.source. 3198 tests pass. Files: `runtime.py`, `engine.py`, `mcp/server.py`. Tests: `test_governance_runtime.py` (19), `test_transport_conformance.py` (8).

### ~~TODO-TRANSPORT-002: Build CLI Adapter~~ (COMPLETED 2026-03-14)

Shipped CLI transport adapter (`toolwright/cli_transport/adapter.py`, `serve.py`). JSONL protocol on stdin/stdout. `toolwright serve --transport cli` wired into CLI. Same governance guarantees as MCP. Tests: `test_cli_transport.py` (14), `test_transport_conformance.py` (8 across MCP+CLI).

### TODO-TRANSPORT-003: Build REST/HTTP API Adapter
- **Priority**: P2 | **Effort**: M
- **What**: Allow `toolwright serve --transport rest` to expose governed tools as a REST API. Endpoints: `GET /v1/tools` (list), `POST /v1/invoke/{tool_name}` (call), `GET /v1/health` (status).
- **Why**: Enables any agent framework (not just MCP-compatible ones) to use governed tools via standard HTTP. Also enables custom integrations, webhooks, and non-Python agents.
- **Details**:
  - New file: `toolwright/rest_transport/adapter.py`
  - Use httpx or lightweight ASGI (starlette) — keep dependencies minimal
  - API key authentication for the REST endpoint itself
  - Standard error responses (401, 403 for governance denials, 404, 429, 500)
  - OpenAPI spec auto-generated from tool manifest
- **Depends on**: TODO-TRANSPORT-001

### TODO-TRANSPORT-004: Transport Conformance Suite
- **Priority**: P1 | **Effort**: M
- **What**: Test suite that runs identical governance scenarios across all transport adapters and asserts identical DecisionTrace output. The critical safety net ensuring governance parity.
- **Why**: Without this, governance behavior could silently drift between transports. A bug in the CLI adapter that bypasses lockfile enforcement would be invisible.
- **Details**:
  - Scenarios: approve, deny_unapproved_tool, deny_breaker_open, deny_rule_violation, deny_network_safety, deny_lockfile_missing
  - For each scenario × each transport: assert DecisionTrace fields match, assert audit log entry matches
  - The hostile QA test: call approved tool via MCP (allowed), call same tool via CLI without lockfile (must be denied)
  - New file: `tests/test_transport_conformance.py`
- **Depends on**: TODO-TRANSPORT-001 + at least one additional adapter

### TODO-TRANSPORT-005: Update positioning and docs
- **Priority**: P1 | **Effort**: S
- **What**: Update README, architecture docs, and CLI help to reflect transport-agnostic governance. Change "MCP tools" language to "AI tools." Add transport selection docs. Update `toolwright config` to generate configs for CLI and REST transports.
- **Why**: The README already says "immune system for AI tools" — the transport-agnostic architecture makes that literally true. Positioning shift attracts CLI-first developers.
- **Details**:
  - README: Add "Any transport. Same governance." section showing MCP/CLI/REST side by side
  - `docs/architecture.md`: Update diagram to show transport-agnostic engine
  - `toolwright config --transport cli|rest|mcp`: Generate appropriate config snippets
  - Update hero demo to show multi-transport governance
- **Depends on**: TODO-TRANSPORT-001

---

## Transport Delight Opportunities (from CEO Strategic Review 2026-03-13)

### TODO-DELIGHT-001: Auto-detect transport mode
- **Priority**: P3 | **Effort**: M
- **What**: `toolwright serve --transport auto` — auto-detect connecting agent's protocol (MCP handshake vs HTTP request vs CLI invocation) and serve accordingly. Like a web server handling HTTP/1.1 and HTTP/2 from the same port.
- **Why**: Users don't have to choose or know about transports. It just works.
- **Depends on**: TODO-TRANSPORT-001, TODO-TRANSPORT-002, TODO-TRANSPORT-003

### TODO-DELIGHT-002: `toolwright wrap` for CLI tools
- **Priority**: P0 | **Effort**: M
- **What**: Extend `toolwright wrap` (currently MCP-only) to wrap any CLI tool with governance. Example: `toolwright wrap gh` governs GitHub CLI calls with lockfile, circuit breakers, and rules. Uses the new CLI transport adapter and GovernanceRuntime.
- **Why**: Killer demo for CLI-first developers. Shows governance works without MCP. CEO identified this as the #1 differentiator for the transport-agnostic story.
- **Details**:
  - `toolwright wrap gh` introspects the CLI tool's help/man page to generate a synthetic tool manifest
  - Wraps subprocess calls through GovernanceRuntime with shell=False, stdin=DEVNULL
  - CLI tool paths validated against approved manifest (prevent path traversal)
  - Handle: tool not on PATH → clean error, subprocess timeout → clean error, non-zero exit → include stderr
- **Depends on**: TODO-TRANSPORT-001 (DONE), TODO-TRANSPORT-002 (DONE)

### TODO-DELIGHT-003: Multi-transport demo panel
- **Priority**: P3 | **Effort**: S
- **What**: Add a "Same governance, any transport" panel to `toolwright demo` showing the same tool call through MCP, CLI, and REST — all producing identical DecisionTrace.
- **Why**: Makes the transport-agnostic value proposition visceral in the demo.
- **Depends on**: TODO-TRANSPORT-004

### TODO-DELIGHT-004: Transport-aware `toolwright create`
- **Priority**: P3 | **Effort**: M
- **What**: `toolwright create --transport cli` auto-generates CLI wrapper scripts. `--transport rest` auto-generates OpenAPI spec for the governed API.
- **Why**: Full lifecycle transport-awareness from create to serve.
- **Depends on**: TODO-TRANSPORT-002, TODO-TRANSPORT-003

### TODO-DELIGHT-005: Token budget estimator
- **Priority**: P2 | **Effort**: S
- **What**: `toolwright estimate-tokens` shows token consumption per transport: "MCP: ~55,000 tokens. CLI: ~800 tokens. REST: ~200 tokens." Addresses the #1 concern in the MCP debate with hard numbers.
- **Why**: Makes the efficiency argument concrete. Marketing gold for CLI-first audience.
- **Depends on**: Nothing (can build standalone)

---

## Viral Launch (from CEO Review 2026-03-13)

**Context**: CEO review determined toolwright has the right product and market but zero awareness. Strategy: lead with the magic moment ("point at any API, get governed tools"), not fear ("your MCP tools have no governance"). Launch on HN Show HN + Twitter/X thread.

### TODO-LAUNCH-001: HN Show HN post + first comment
- **Priority**: P1 | **Effort**: S
- **What**: Write the Show HN post title, body, and first comment (technical deep dive). Prepare as markdown files in `docs/launch/`.
- **Why**: The HN launch is the single highest-leverage distribution event. The first comment sets the narrative. Prepared materials outperform improvised ones.
- **Details**:
  - Title: "Show HN: Toolwright – Point at any API, get governed AI tools in 10 seconds"
  - First comment: what it does, how it works, why you built it, what's next, honest about alpha
  - Include live demo URL or instructions that work on first try
- **Depends on**: All P0/P1 items shipped

### TODO-LAUNCH-002: Twitter/X launch thread
- **Priority**: P1 | **Effort**: S
- **What**: 5-7 tweet thread showing the magic moment with GIFs/screenshots. Prepared as markdown in `docs/launch/`.
- **Why**: Twitter is where developer tool launches get amplified. The thread needs to be visual and shareable.
- **Depends on**: TODO-LAUNCH-001 (same content, different format)

### TODO-LAUNCH-003: `toolwright score` — governance maturity scanner
- **Priority**: P2 | **Effort**: S (2-3 hours)
- **What**: Rate any toolwright-managed project's governance maturity (0-100, letter grade A-F). Checks: has lockfile? Signatures verified? Rules defined? Circuit breakers active? Drift monitoring on?
- **Why**: Marketing tool for post-launch engagement. "Score your MCP setup!" Screenshots well. Creates shareable content.
- **Details**:
  - Scoring rubric: lockfile exists (20pts), signatures verified (20pts), rules defined (15pts), circuit breakers configured (15pts), drift monitoring active (15pts), auth configured (15pts)
  - Output: letter grade + score + breakdown + suggestions to improve
  - New file: `toolwright/cli/score.py`
- **Depends on**: C0 fix (signature verification must work for scoring to be meaningful)

### TODO-LAUNCH-004: `toolwright why <tool>` — debugging command
- **Priority**: P2 | **Effort**: S (1-2 hours)
- **What**: Explain why a specific tool is blocked/quarantined/degraded. Shows the lockfile entry, rule violations, circuit breaker state.
- **Why**: Power users navigating governance need a single command to understand tool state. Like `brew info` or `pip show`.
- **Details**:
  - Check lockfile status (approved/pending/blocked)
  - Check circuit breaker state (closed/open/half_open)
  - Check rule violations (which rules would block this tool)
  - Check drift status (any pending drift events)
- **Depends on**: Nothing

### TODO-LAUNCH-005: GitHub Action for CI governance
- **Priority**: P2 | **Effort**: M (half day)
- **What**: Reusable GitHub Action that runs `toolwright gate check` and `toolwright verify` on PRs. Badge for README: "tools governed by toolwright".
- **Why**: Distribution channel — every repo using the action advertises toolwright. Social proof through badges.
- **Details**:
  - `.github/actions/toolwright-verify/action.yml`
  - Inputs: toolpack path, verification mode, Python version
  - Outputs: pass/fail, tool count, governance score
  - Badge: `![Governed by Toolwright](https://img.shields.io/badge/governed%20by-toolwright-blue)`
- **Depends on**: C0 fix, stable CLI interface
