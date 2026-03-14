# Toolwright CEO Dogfood Report

**Date**: 2026-03-14 (Round 3 — Comprehensive)
**Version**: toolwright 1.0.0a2
**Branch**: feature/ceo-review-phase1
**Test Suite**: 3120 tests passing (50.59s)
**Methodology**: 6 parallel dogfood teams + CEO hands-on E2E testing across all pillars

---

## Executive Summary

Comprehensive dogfooding across all 5 pillars (CONNECT, GOVERN, CORRECT, HEAL, KILL), MCP server, and advanced workflows. Tested from multiple user personas: first-time user, CI/automation, power user, API provider. Tested real workflows with GitHub, Stripe, and Petstore APIs.

**Overall Assessment**: Toolwright is functionally solid with excellent architecture. The core workflows work end-to-end. The main risks are UX friction points that would cause first-time users to abandon the tool before seeing its value.

| Category | Critical | High | Medium | Low | Cosmetic |
|----------|----------|------|--------|-----|----------|
| CONNECT  | 1 | 2 | 3 | 2 | 2 |
| First-Run UX | 0 | 1 | 3 | 7 | 5 |
| GOVERN/CORRECT | 0 | 2 | 3 | 4 | 3 |
| HEAL | 0 | 0 | 3 | 2 | 0 |
| KILL | 0 | 1 | 1 | 0 | 0 |
| MCP Server | 0 | 0 | 1 | 2 | 0 |
| Advanced | 0 | 0 | 1 | 1 | 0 |
| CEO E2E | 0 | 1 | 2 | 1 | 0 |
| **TOTAL** | **1** | **7** | **17** | **19** | **10** |

---

## CRITICAL (Ship Blocker)

### C1: Tool descriptions are token bombs (CONNECT)
- **Impact**: Production blocker for LLM consumption
- **Details**: GitHub toolpack has 491/1062 tools with descriptions over 5,000 chars. Stripe has 259/553 tools over 20,000 chars. Longest single description: 29,609 chars. The bulk is "(Call X first to obtain Y)" hints repeated dozens of times.
- **Consequence**: A GitHub toolpack = ~3.5M chars of tool descriptions. Even with `--scope`, this overwhelms LLM context windows.
- **Fix**: Truncate descriptions to ~500 chars by default, move prerequisite hints to a separate field, or use `--verbose-tools` flag to control expansion (currently exists but default needs to be compact).

---

## HIGH Priority

### H1: `ship` ignores `--no-interactive` flag (First-Run)
- **Impact**: Blocks CI/automation and agent usage
- **Details**: `toolwright --no-interactive ship` still prompts for "API URL to capture:" — hangs waiting for input
- **Fix**: Respect the `--no-interactive` flag or require URL as a positional argument

### H2: OpenAPI specs with relative/missing server URLs silently fall back to `api.example.com` (CONNECT)
- **Impact**: Any user with a non-trivial OpenAPI spec gets a broken, unusable toolpack with no warning
- **Details**: Petstore spec (`/api/v3` relative URL) and specs with no `servers` field both silently resolve to `api.example.com`. The toolpack appears valid but every API call fails at runtime.
- **Fix**: (a) Resolve relative URLs against the fetch URL, (b) Derive host from spec URL when possible, (c) At minimum, warn the user and suggest `--base-url`

### H3: `--base-url` override rejected by host allowlist (CEO E2E)
- **Impact**: Users who specify `--base-url` to override the host can't actually use it — blocked by allowlist
- **Details**: `toolwright serve --base-url https://petstore3.swagger.io/api/v3` fails with "Host 'petstore3.swagger.io' is not allowlisted for action host 'api.example.com'"
- **Fix**: When `--base-url` is specified, automatically add its host to the allowed hosts for the session

### H4: `kill` accepts nonexistent/arbitrary tool IDs without validation (KILL)
- **Impact**: Typos go unnoticed, phantom tools appear in quarantine
- **Details**: `toolwright kill totally_fake_tool --reason "test"` succeeds silently. The tool appears in quarantine.
- **Fix**: Validate tool IDs against the lockfile/toolpack. Warn if tool doesn't exist.

### H5: `status` output suggests `gate allow` without `--all` flag (CEO E2E)
- **Impact**: Every user following the guided next-step gets an error
- **Details**: `status` says "Next -> toolwright gate allow --toolpack github" but this fails with "Specify tool IDs to approve or use --all". The suggestion should include `--all`.
- **Fix**: Update status output to include `--all` in the suggested command

### H6: `enforce --mode evaluate` starts HTTP server instead of evaluating and exiting (GOVERN)
- **Impact**: Core governance evaluation feature is broken — cannot evaluate policies in batch
- **Details**: `toolwright enforce --mode evaluate` unconditionally starts an HTTPServer on port 8080 and blocks forever, regardless of mode. Evaluate mode should run evaluation and exit.
- **Fix**: Check mode before starting server in `run_enforce()`

### H7: Duplicate rule ID causes unhandled ValueError traceback (CORRECT)
- **Impact**: Raw Python traceback shown to user
- **Details**: `toolwright rules add --rule-id existing-id` throws unhandled `ValueError` with full traceback instead of clean error message
- **Fix**: Catch `ValueError` in CLI layer and show friendly error

---

## MEDIUM Priority

### M1: `display_name: null` in non-recipe toolpack.yaml (CONNECT)
- Spec-based creates don't derive display_name from spec title or filename

### M2: Contract marks optional PUT body fields as required (CONNECT)
- PUT endpoint schemas copy requirements from POST schema instead of their own

### M3: Config output `--root` may point to wrong directory (CONNECT)
- Generated MCP config may reference a non-existent `.toolwright` path

### M4: `doctor` gives unhelpful error in fresh project after `init` (First-Run)
- Should show a diagnostic checklist, not just "No toolpacks found"

### M5: `serve` shows raw Python errno on missing file (First-Run)
- `Error: [Errno 2] No such file or directory:` instead of user-friendly message

### M6: `kill` confirmation prompt not respected by `--no-interactive` global flag
- Kill still prompts when `--no-interactive` is set globally (needs per-command `--yes` or `-y` flag)

### M7: `health` missing summary counts (HEAL)
- With 1062 tools, no summary breakdown — just "Some tools are unhealthy"

### M8: `health` rate-limited endpoints conflated with genuinely unhealthy (HEAL)
- 553/571 "unhealthy" are actually rate-limited — misleading severity picture

### M9: `verify` default mode fails without guidance (HEAL)
- `toolwright verify` requires `--playbook` but doesn't suggest `--mode contracts` as alternative

### M10: Double-kill silently overwrites reason (KILL)
- Killing an already-killed tool overwrites the reason with no warning or audit trail

### M11: `inspect` doesn't accept `--toolpack` flag (MCP Server)
- Requires knowing internal artifact directory structure; inconsistent with `serve`

### M12: `wrap` shows raw Python traceback on bad upstream (Advanced)
- 40+ line traceback instead of clean one-line error message
- Also: help examples like `toolwright wrap npx -y ...` fail because Click parses `-y` — needs `--` separator

### M13: `config` output doesn't include full binary path (CEO E2E)
- Uses `"command": "toolwright"` which fails if venv isn't activated

### M14: Share/install creates nested `toolpacks/toolpacks/` directory (CEO E2E)
- Installed toolpack not found by auto-detection. `toolwright status` can't find it after install.

### M15: `status` shows `[OK]` for Lockfile when tools are blocked (GOVERN)
- Status indicator is misleading: shows `[OK]` even with blocked tools. `gate check` correctly fails.

### M16: Lockfile `generated_at` timestamp is epoch zero (GOVERN)
- Both lockfile variants show `1970-01-01T00:00:00+00:00` instead of actual generation time

### M17: Sequence rule kind has no CLI options for configuration (CORRECT)
- `rules add --kind sequence` creates a rule with `required_order: []` (no-op). No CLI flags exist to configure it.

---

## LOW Priority

1. `estimate-tokens` help text has broken formatting (literal `\b` characters)
2. Inconsistent exit codes for "no toolpack found" across commands (exit 1 vs 2)
3. `health` error message doesn't suggest toolpack auto-resolution like other commands
4. `lint` doesn't auto-resolve toolpack like other commands
5. `--verbose` flag produces no visible output for most commands
6. `groups list` error references wrong command (`compile` instead of `create`)
7. `gate allow` with no args gives confusing error about missing lockfile
8. `use --clear` succeeds even when no default is set ("Default cleared" when nothing was set)
9. `drift` bare invocation doesn't mention `--shape-baselines` mode
10. `watch` doesn't explain where reconciliation loop runs (it runs in `serve`)
11. `groups` bare command fails (only `groups list` works, inconsistent with `snapshots`)
12. Bad grammar in auto-generated descriptions (e.g., "Delete a suspended by {installation_id}")
13. `--help-all` duplicates commands without clear visual separation from Quick Start/Operations
14. Paths show `/private/tmp/` instead of `/tmp/` on macOS (symlink resolution)
15. Mint auth detection says "redirect" for Bearer token auth

---

## COSMETIC

1. `repair plan` exits 0 when no plan exists (could mislead CI)
2. `use --clear` succeeds when nothing is set
3. Risk classification may over-calibrate for common CRUD patterns (user creation = "high")
4. `recipes` bare command shows list (works but inconsistent with other group commands)
5. `--no-rules` flag works correctly (positive)
6. Error messages for unknown recipes are excellent (positive)
7. Config `--format` flag works for json/yaml/codex but no `--client` flag despite help mentioning "Claude, Cursor, Codex"

---

## Strengths (What's Working Well)

1. **Demo command** — Excellent onboarding moment. Clean, fast, impressive proof-of-governance
2. **Error messages** — Generally excellent. Unknown recipe error is a model for all commands
3. **Tool limit safety** — Refuses to serve >200 tools with helpful scope suggestions
4. **MCP protocol compliance** — Clean JSON-RPC 2.0, proper initialize/tools-list flow
5. **Rich filtering** — `--scope`, `--toolset`, `--max-risk`, `--tool-filter` combine cleanly
6. **Recipe-based creation** — GitHub and Stripe recipes work seamlessly
7. **Drift detection** — Shape drift with severity classification is well-designed
8. **Kill/enable cycle** — Clean, well-implemented workflow
9. **Token estimation** — Unique, practical feature comparing transport modes
10. **Multi-toolpack handling** — `use` command and auto-detection work well
11. **Groups** — 170 auto-generated groups make scope selection discoverable
12. **Ed25519 signing** — Cryptographic governance feels production-grade
13. **Bundle determinism** — Zeroed timestamps for reproducibility
14. **HTTP transport** — Bonus web console UI when using `--http`
15. **3120 tests passing** — Solid test coverage in 51s

---

## User Persona Analysis

### First-Time User (Junior Dev)
- **Journey**: `pip install toolwright` → `toolwright init` → `toolwright demo` → `toolwright create github`
- **Friction**: Will struggle with `gate allow` (missing `--all`), get confused by `api.example.com` for non-recipe specs, may not understand what a "playbook" is for `verify`
- **Rating**: 7/10 — Good but some stumbling blocks on the golden path

### CI/Automation Engineer
- **Journey**: `toolwright create --spec $SPEC --no-interactive` → `gate allow --all --no-interactive` → `serve`
- **Friction**: `ship` ignores `--no-interactive`, config output doesn't include full binary path, exit codes inconsistent, kill needs `-y` separately from `--no-interactive`
- **Rating**: 6/10 — Several blockers for fully non-interactive usage

### API Provider (Security-Conscious)
- **Journey**: Create toolpack → review policies → gate specific tools → serve with lockfile
- **Friction**: `kill` accepts phantom tool IDs, health summary is hard to parse, token bomb descriptions
- **Rating**: 8/10 — Governance model is strong, needs polish

### Power User (Multi-API)
- **Journey**: Multiple toolpacks, scoped serving, behavioral rules, drift monitoring, share/install
- **Friction**: Minor — mainly UX inconsistencies between commands, share/install nesting bug
- **Rating**: 9/10 — Most complete experience

---

## Recommended Fix Priority

### Sprint 1 (Ship Blockers — do these before any release)
1. **C1**: Cap tool descriptions at ~500 chars by default
2. **H2**: Warn/fail on `api.example.com` fallback for OpenAPI specs
3. **H5**: Fix `status` to suggest `gate allow --all`
4. **H3**: Auto-add `--base-url` host to session allowlist
5. **H6**: Fix `enforce --mode evaluate` to not start HTTP server
6. **H7**: Catch duplicate rule ID error in CLI layer

### Sprint 2 (User Experience — critical for adoption)
7. **H4**: Validate kill tool IDs against lockfile
8. **H1**: Make `ship` respect `--no-interactive`
9. **M14**: Fix share/install directory nesting
10. **M13**: Use full binary path in config output
11. **M12**: Catch wrap connection errors, fix help examples
12. **M15**: Fix status `[OK]` indicator when tools are blocked
13. **M16**: Fix lockfile `generated_at` epoch zero timestamp

### Sprint 3 (Polish — quality of life)
14. **M1-M11, M17**: Various medium-priority UX fixes
15. **L1-L15**: Low-priority polish items
16. Cosmetic fixes (grammar, formatting, consistency)
