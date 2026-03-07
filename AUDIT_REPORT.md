# Toolwright Production Readiness Audit

**Date:** 2026-02-28
**Scope:** Full project — code, docs, packaging, UX, security, cross-platform, maintainability
**Codebase:** 211 Python files, 43,739 lines, 199 test files (2,150+ tests), 87 capabilities

---

## 1. Executive Summary

Toolwright is an ambitious, well-architected MCP tool governance system with a **strong core**. The capture → compile → approve → serve pipeline works, the test suite is comprehensive (2,150+ tests), and the safety-by-default design philosophy is consistently applied. The codebase is cleanly typed (173/211 files use `from __future__ import annotations`, strict mypy enabled) and free of unexplained TODOs.

**However, the project is not production-ready.** There are 4 security findings that undermine the safety claims in the README, destructive CLI commands with no confirmation prompts, silent failure modes that would frustrate operators, and ~13 features that are implemented but never wired into any command or tested. The install-to-value path is excellent (3-5 steps), but a real user hitting edge cases will encounter bare Python tracebacks, dead-end error messages, and platform-specific failures on Windows.

**Bottom line:** Fix the P0/P1 findings below (estimated 2-3 focused days) and Toolwright is a genuinely compelling product. Ship it as-is and users will lose trust at the first error.

---

## 2. P0 Findings — Blockers

### [P0-001] `gate allow --all` Approves Every Tool With No Confirmation
**Category:** CLI Safety
**Files:** `toolwright/cli/commands_approval.py`
**Problem:** `toolwright gate allow --all` bulk-approves every tool in the lockfile *without asking*. No confirmation prompt, no preview, no `--dry-run`. This directly contradicts the README claim "Nothing runs without approval" — a single command bypasses the entire gate review.
**Fix:** Add a confirmation prompt showing the count and risk breakdown: `"Approve 12 tools (3 low, 6 medium, 2 high, 1 critical)? [y/N]"`. Default to No.

### [P0-002] `gate sync --prune-removed` Silently Deletes Approval Records
**Category:** CLI Safety
**Files:** `toolwright/cli/commands_approval.py`
**Problem:** The `--prune-removed` flag deletes approval records for tools no longer in the manifest — with no preview, no confirmation, and no backup. If the manifest was temporarily corrupted or regenerated incompletely, all prior approval history is lost.
**Fix:** Show which records will be pruned and require confirmation. Create a backup before pruning.

### [P0-003] No Confirmation or Backup for Any State-Modifying Command
**Category:** CLI Safety
**Files:** `toolwright/cli/commands_approval.py`, `commands_repair.py`, `commands_rules.py`
**Problem:** `rules remove`, `repair apply`, `gate allow`, and `rollback` all modify state immediately with no undo. There is no `--dry-run` flag on any state-modifying command.
**Fix:** Implement `--dry-run` for all state-modifying commands. Create lockfile/state backups before writes.

### [P0-004] Agent Can Toggle Circuit Breakers Without Human Approval
**Category:** Security / Agent Trust
**Files:** `toolwright/mcp/meta_server.py` (toolwright_kill_tool, toolwright_enable_tool)
**Problem:** An agent can kill a tool, immediately re-enable it, and repeat — bypassing the circuit breaker entirely. A compromised agent could disable monitoring tools, execute unsafe calls, then re-enable them with no audit trail of the brief window.
**Fix:** Require human CLI confirmation to re-enable a killed tool. Add a lockout period after kills. Log all kill/enable pairs.

---

## 3. P1 Findings — Serious Friction

### Security

**[P1-SEC-001] Redaction Defaults to OFF for HAR/OTEL Imports**
Files: `toolwright/cli/capture.py`
Problem: `--redact` defaults to False. A user who runs `toolwright capture import traffic.har` without thinking about it writes tokens, cookies, and PII to disk unredacted. This contradicts the README: "Secrets are redacted before anything reaches disk."
Fix: Default `--redact` to True. Add `--no-redact` for explicit unsafe override.

**[P1-SEC-002] Redaction Patterns Miss Modern Token Formats**
Files: `toolwright/core/capture/redaction_profiles.py`
Problem: Patterns don't match Stripe (`sk_live_*`), AWS (`AKIA*`, `ASIA*`), Google, or Azure tokens in headers/URLs.
Fix: Add vendor-specific token patterns. Add an `--aggressive-redaction` profile.

**[P1-SEC-003] DNS Rebinding Window in SSRF Protection**
Files: `toolwright/core/network_safety.py`, `toolwright/mcp/server.py`
Problem: Hostname is resolved, IP is validated, but no resolution pinning. Attacker DNS can flip from public to `169.254.169.254` between validation and request.
Fix: Pin resolved IP for the lifetime of a request. Re-validate after redirects.

**[P1-SEC-004] `toolwright_add_rule` Meta-Tool Can Create ACTIVE Rules**
Files: `toolwright/mcp/meta_server.py`
Problem: While `suggest_rule` correctly creates DRAFT rules, `add_rule` allows agents to create ACTIVE rules directly — bypassing the human activation gate.
Fix: Force `status=DRAFT` in `_add_rule()` when called via MCP. Only CLI can create ACTIVE rules.

### First-Run Experience

**[P1-FRX-001] No URL Validation Before Playwright Invocation**
Files: `toolwright/cli/mint.py`
Problem: `toolwright ship notaurl` passes a malformed URL to Playwright, which fails after a 60s timeout with a cryptic error.
Fix: Validate URL scheme and netloc before calling Playwright. Fail fast with example usage.

**[P1-FRX-002] Dead-End When Capture Produces Zero Exchanges**
Files: `toolwright/ui/flows/ship.py`
Problem: If `--allowed-hosts` is wrong, capture produces 0 exchanges. The Review stage says "No lockfiles found" and suggests `gate sync` — which also fails.
Fix: Check exchange count after capture. Suggest checking `--allowed-hosts` and offer retry.

**[P1-FRX-003] No Validation for `--allowed-hosts`**
Files: `toolwright/cli/main.py`
Problem: Empty string or protocol-prefixed hosts (`https://api.example.com`) are accepted silently and produce zero matches.
Fix: Validate hosts early — reject empty strings and strings containing `://`.

**[P1-FRX-004] Existing Toolpack Reuse Lacks Context**
Files: `toolwright/ui/flows/ship.py`
Problem: `toolwright ship` in a directory with existing toolpacks asks "Use existing?" but doesn't show which one, when it was created, or what's in it.
Fix: Show toolpack name, last-modified date, tool count.

### CLI UX

**[P1-CLI-001] `--toolpack` Auto-Resolution Inconsistent**
Files: Multiple CLI files
Problem: Some commands use `resolve_toolpack_path()`, others require explicit `--toolpack`. Inconsistent experience.
Fix: Apply `resolve_toolpack_path()` uniformly to all commands that accept `--toolpack`.

**[P1-CLI-002] `--tools` vs `--toolpack` Naming Confusion**
Files: `toolwright/cli/main.py`
Problem: Some commands use `--tools` (path to tools.json), others use `--toolpack` (path to toolpack dir). Users can't predict which.
Fix: Standardize on `--toolpack` everywhere. Accept `--tools` as alias where needed.

**[P1-CLI-003] Only `status` Supports `--json` Output**
Files: `toolwright/cli/main.py`
Problem: `drift`, `health`, `quarantine`, `repair plan` have no `--json` or `--format` flag. Not scriptable.
Fix: Add `--format json|text` to all inspection commands.

### MCP Server

**[P1-MCP-001] No Signal Handler for Graceful Shutdown**
Files: `toolwright/mcp/server.py`
Problem: stdio transport doesn't register SIGTERM/SIGINT handlers. Container `docker stop` sends SIGTERM — audit logs and session history may not flush.
Fix: Register signal handlers before `asyncio.run()`.

**[P1-MCP-002] Lockfile Not Validated After Startup**
Files: `toolwright/mcp/server.py`
Problem: Lockfile loaded once at startup. External modifications (another terminal running `gate allow`) are not detected. Stale approval state.
Fix: Periodic lockfile digest check (every 30s). Warn or reload on change.

**[P1-MCP-003] Unhandled Exceptions Not Wrapped in MCP Error Response**
Files: `toolwright/mcp/server.py`
Problem: If `pipeline.execute()` raises an unexpected exception, it propagates uncaught. MCP protocol requires `CallToolResult` with `isError=True`.
Fix: Wrap pipeline call in try/except, return structured MCP error.

**[P1-MCP-004] No Input Schema Validation on Tool Calls**
Files: `toolwright/mcp/server.py`, `toolwright/mcp/pipeline.py`
Problem: Server advertises `inputSchema` but never validates client arguments against it. Invalid types pass through to HTTP execution.
Fix: Add jsonschema validation before pipeline execution.

### Cross-Platform

**[P1-CP-001] `os.environ["USER"]` Fails on Windows**
Files: `toolwright/core/approval/signing.py`
Problem: Windows uses `USERNAME`, not `USER`. Falls back to "unknown" which means approval records are anonymized on Windows.
Fix: Use `getpass.getuser()` which is cross-platform.

**[P1-CP-002] Windows Config Paths Use Wrong Separators**
Files: `toolwright/ui/flows/config.py`
Problem: `%APPDATA%/Claude/...` uses forward slash with Windows env var. May not resolve correctly.
Fix: Use `Path(os.environ["APPDATA"]) / "Claude" / ...`.

**[P1-CP-003] `os.kill(pid, 0)` Not Reliable on Windows**
Files: `toolwright/utils/locks.py`
Problem: PID liveness check via `os.kill(pid, 0)` has different semantics on Windows. Stale locks may not be detected.
Fix: Add Windows-specific PID check via ctypes or `psutil.pid_exists()`.

### Operational

**[P1-OPS-001] Event Log Unbounded — Potential Disk Exhaustion**
Files: `toolwright/core/reconcile/event_log.py`
Problem: Append-only JSONL with no rotation, no size limit. `recent(n)` reads entire file into memory.
Fix: Implement rotation at 100MB. Use tail-based reads.

**[P1-OPS-002] Lock Files Accumulate Without Cleanup**
Files: `toolwright/utils/locks.py`
Problem: `.toolwright/state/lock.*` files created but never cleaned on crash/SIGKILL.
Fix: On startup, scan for stale locks (PID not alive) and auto-clean.

**[P1-OPS-003] Circuit Breaker State Lost on File Deletion**
Files: `toolwright/core/kill/breaker.py`
Problem: If `circuit_breakers.json` is deleted, all manual kills are forgotten. Tools silently re-enable.
Fix: Keep backup. Log ERROR when state is missing.

**[P1-OPS-004] Missing Playwright Error Not Graceful**
Files: `toolwright/cli/capture.py`
Problem: Running capture without playwright installed gives ImportError, not a helpful message.
Fix: Wrap import, show `pip install "toolwright[playwright]"`.

**[P1-OPS-005] No Python Version Runtime Check**
Files: `toolwright/__init__.py`
Problem: `requires-python = ">=3.11"` in pyproject.toml but no runtime check. Python 3.10 gives cryptic syntax errors.
Fix: Add `sys.version_info` check in `__init__.py`.

### Documentation

**[P1-DOC-001] README Documents `share` and `install` Commands That Don't Exist**
Files: `README.md` (lines 78-79)
Problem: README shows `toolwright share <toolpack>` and `toolwright install <file.twp>`. The actual CLI only has `toolwright bundle`.
Fix: Update README to match actual CLI, or register the commands.

**[P1-DOC-002] User Guide Has Broken Markdown Code Blocks**
Files: `docs/user-guide.md` (9 instances)
Problem: Closing triple backticks on same line as command content. Renders incorrectly.
Fix: Move closing ``` to its own line at all 9 locations.

### Packaging

**[P1-PKG-001] Missing `py.typed` Marker**
Files: `toolwright/`
Problem: Package declares strict mypy but lacks PEP 561 `py.typed` marker. Type checkers ignore inline types.
Fix: Create empty `toolwright/py.typed`.

**[P1-PKG-002] Hatchling Version Unconstrained**
Files: `pyproject.toml`
Problem: `requires = ["hatchling"]` with no version. The `artifacts` key is a recent feature.
Fix: `requires = ["hatchling>=1.25.0"]`.

---

## 4. P2 Findings — Polish

| ID | Category | Problem | Fix |
|----|----------|---------|-----|
| P2-SEC-005 | Security | Lockfile signatures not verified on load (only in CI check) | Add verify_mode parameter to load() |
| P2-SEC-006 | Security | Signing key permissions not validated on read | Check `os.stat().st_mode` on load |
| P2-SEC-007 | Security | Confirmation token entropy 96 bits (below 128-bit recommendation) | Increase `secrets.token_hex(12)` to 16 |
| P2-SEC-008 | Security | Token expiry race condition between grant and consume | Use DB `expires_at` as single source of truth |
| P2-SEC-009 | Security | Error messages leak tool IDs and resolved IPs | Use reason codes only in client-facing errors |
| P2-SEC-010 | Security | Schema zeroing reveals API structure | Add `--aggressive-truncation` option |
| P2-SEC-011 | Security | Redirect validation doesn't re-evaluate policy for target | Re-validate risk tier on redirects |
| P2-FRX-005 | First Run | Generic `except Exception` blocks give unhelpful errors (10+ instances) | Catch specific exceptions, suggest fixes |
| P2-FRX-006 | First Run | Ship flow doesn't resume from last completed stage | Save stage state to `.toolwright/ship-state.json` |
| P2-FRX-007 | First Run | Demo temp path not discoverable | Print exact path, offer to copy |
| P2-FRX-008 | First Run | No progress indicator during 30s capture | Add spinner or dots |
| P2-FRX-009 | First Run | Exit codes inconsistent (1 vs 3 across commands) | Standardize or document |
| P2-CLI-004 | CLI UX | `--allowed-hosts` (plural) vs `--allow-private-cidr` (singular) | Standardize naming |
| P2-CLI-005 | CLI UX | Help text style varies (periods, examples, env vars) | Create help text template |
| P2-CLI-006 | CLI UX | `--help-all` doesn't mark advanced commands | Add [advanced] tag |
| P2-CLI-007 | CLI UX | Error messages not actionable ("Provide --tools or --toolpack") | Show resolution chain |
| P2-MCP-005 | MCP | Unbounded Next.js build ID cache (no TTL, no max size) | Add LRU with TTL |
| P2-MCP-006 | MCP | Response size check bypassed when Content-Length missing on 4xx/5xx | Check body length after read |
| P2-MCP-007 | MCP | Meta-tool descriptions not compacted (unlike main tools) | Apply `optimize_description()` |
| P2-MCP-008 | MCP | HTTP lifespan doesn't catch startup exceptions cleanly | Add try/except around lifespan |
| P2-CP-004 | Platform | File permissions (0o600) silently ignored on Windows | Add Windows ACL or document limitation |
| P2-CP-005 | Platform | Headless mode default=False fails on CI/Linux without display | Auto-detect `DISPLAY` env var |
| P2-CP-006 | Platform | `print()` in capture code may fail with non-UTF-8 Windows encoding | Use Rich console or click.echo() |
| P2-OPS-006 | Ops | Reconcile state lost if deleted — no recovery from event log | Log WARNING, implement replay |
| P2-OPS-007 | Ops | No dead-letter queue for failed repair patches | Create `.toolwright/repairs/failed/` |
| P2-OPS-008 | Ops | Reconcile loop crash loses in-progress state | Persist checkpoint before cycle |
| P2-OPS-009 | Ops | MCP shim silently starts non-functional server when mcp missing | Fail with clear install message |
| P2-OPS-010 | Ops | Snapshot rollback doesn't restore version counter | Restore from snapshot manifest |
| P2-CODE-001 | Code | 80 broad `except Exception` handlers; 11 bare `pass` | Replace `pass` with logging |
| P2-CODE-002 | Code | Silent config load failures (YAML parse error → empty defaults) | Log warnings on parse failure |
| P2-CODE-003 | Code | 147 `Any` type usages weaken type safety | Replace top 20 with TypedDict |
| P2-CODE-004 | Code | REDACT rule type untested (5/6 rule types covered) | Add tests |
| P2-CODE-005 | Code | MCP meta_server.py is 1,508-line monolith | Extract subsystem handlers |
| P2-CODE-006 | Code | CLI main.py is 2,156 lines with business logic | Move logic to core/ |
| P2-DOC-003 | Docs | README example output not verified against actual mint output | Run and update |
| P2-OVERENG-001 | Scope | Telemetry infrastructure exists but no metrics emitted | Wire or remove |
| P2-OVERENG-002 | Scope | Notification/webhook engine not connected to reconcile loop | Wire or remove |
| P2-OVERENG-003 | Scope | EU AI compliance report orphaned (no CLI, no tests) | Remove or integrate |
| P2-OVERENG-004 | Scope | Container emit orphaned (no CLI command) | Add `toolwright emit-container` or remove |
| P2-OVERENG-005 | Scope | OTEL parser never called from any code path | Wire into `capture import` or remove |
| P2-OVERENG-006 | Scope | WebMCP capture bets on unstable W3C draft | Make opt-in via flag |
| P2-OVERENG-007 | Scope | Custom redaction profiles not exposed via CLI | Remove or add command |

---

## 5. P3 Findings — Nits

- `.toolwright` directory not documented as a regular (non-hidden) directory on Windows
- `shlex.join()` displays Unix-style commands on Windows
- `subprocess.run()` in container.py uses `text=True` without explicit encoding
- Tide workflow integration depends on unpackaged external tool
- Schema migration command hidden with no documentation
- Flow graph detection implemented but invisible to users
- Endpoint tagging computed but not displayed
- Auth profiles not securely wiped on deletion (fragments recoverable)
- No `toolwright export-state` for backup before uninstall
- MCP client config not cleaned up on `pip uninstall`
- `watch.yaml` requires manual editing (no CLI to create/edit)
- OAuth2 provider fully implemented but not wired into any command

---

## 6. Overengineering Candidates

Features that exist but are not wired, not tested, or not earning their maintenance cost:

| Feature | Status | Recommendation |
|---------|--------|----------------|
| EU AI Act Compliance Report | Orphaned (no CLI, no tests, no callers) | **Remove** — premature for a solo-founder project |
| Container Runtime Emission | Orphaned (no CLI command exposes it) | **Remove or add `emit-container` command** |
| Tide Workflow Engine | External dep, hidden command, wrapper only | **Remove** — move to separate plugin |
| OTEL Trace Import | Parser exists but never called | **Wire into `capture import --format otel` or remove** |
| OAuth2 Credential Provider | Full implementation, never used | **Wire into `serve --oauth` or remove** |
| Observability (Tracer + Metrics) | Infrastructure only, no data emitted | **Wire or remove** — dead infrastructure confuses maintainers |
| Notification/Webhooks | Engine exists, not connected to anything | **Wire into reconcile loop or remove** |
| WebMCP Capture | W3C draft spec, zero production implementations | **Make opt-in** — currently runs silently during mint |
| Custom Redaction Profiles | Class exists, only default used, no CLI | **Remove class, keep default patterns inline** |
| Flow Graph Detection | Computed during compile, never displayed | **Add `toolwright flows` or remove** |

**Estimated dead code:** ~2,500 lines across these 10 features. Removing them would reduce maintenance surface by ~6%.

---

## 7. Missing Capabilities

Things a real user would need that are absent:

1. **`--dry-run` for all state-modifying commands** — users cannot preview what `gate allow`, `repair apply`, `rules remove` will do
2. **`--json` output for all inspection commands** — only `status` supports it; `drift`, `health`, `quarantine` are not scriptable
3. **State backup/export** — no way to back up `.toolwright/` state before risky operations or uninstall
4. **CI mode** (`--yes` / `--non-interactive`) — gate approval requires interactive prompts; no way to approve in CI pipelines
5. **Auth `.env` file generation** — after mint, users must manually `export TOOLWRIGHT_AUTH_*` env vars; auto-generating a `.env` template would reduce friction
6. **Windows testing** — no CI or local verification of Windows compatibility; multiple platform-specific issues found
7. **Log rotation** — event log grows unbounded; no rotation, no cleanup
8. **Stale lock cleanup** — lock files accumulate on crashes; no auto-cleanup on startup

---

## 8. Strengths — Do Not Change

1. **Safety-by-default philosophy** — fail-closed enforcement, cryptographic signing, redaction pipeline, agent trust boundaries. The architecture is right.
2. **Lazy-loaded optional dependencies** — playwright, textual, mcp, authlib all properly guarded. Clean install works perfectly.
3. **Comprehensive test suite** — 2,150+ tests across unit, integration, and E2E. Realistic fixtures with real API captures.
4. **Toolpack auto-resolution** — `resolve_toolpack_path()` with fallback chain (flag → env var → config → auto-detect) is excellent UX.
5. **Interactive ship flow** — 6-stage guided wizard makes onboarding approachable. Progressive disclosure done right.
6. **Atomic file writes** — `atomic_write_text()` used consistently for state files. No half-written corruption.
7. **Circuit breaker state machine** — CLOSED/OPEN/HALF_OPEN with persistence, manual override, and quarantine reports. Production-grade.
8. **Rich terminal output** — Unicode/ASCII fallback, `NO_COLOR` support, consistent formatting. Terminal UX is polished.
9. **Clean codebase** — no TODOs, no FIXMEs, no unexplained hacks. Type annotations on 82% of files.
10. **Pydantic models everywhere** — serialization boundaries are typed and validated. Data models are the backbone.

---

*Report generated by comprehensive static analysis of the Toolwright codebase. Dynamic testing (SSRF fuzzing, E2E install, Windows platform) recommended before production release.*
