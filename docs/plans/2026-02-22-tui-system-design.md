# Cask TUI System — Design & Implementation Plan

## Context

Cask is a governance layer for AI agent tools. The core value proposition is the lifecycle loop: **capture → compile → review → approve → serve → verify → drift detect → repair**. The current TUI uses Rich with basic numbered menus, no progress feedback, and no unified narrative flow. The goal is to make the TUI experience **magical** — every command knows what came before and what comes next, the lifecycle loop feels inevitable and effortless, and the demo experience ("fail → diagnose → diff → approve → verify → resume") lands immediately with staff engineers and platform teams.

The TUI is a **narrative engine**, not a collection of screens.

---

## Architecture

### Module Structure

```
toolwright/ui/
├── console.py          # Rich theme, stderr console, SymbolSet (Unicode/ASCII)
├── policy.py           # Interactive mode detection (unchanged)
├── prompts.py          # Enhanced prompt primitives
│                       #   prompt_action() uses prompt-toolkit in fancy mode,
│                       #   readline fallback in plain mode
├── echo.py             # Command echo (unchanged)
├── discovery.py        # Artifact discovery (unchanged)
├── ops.py              # Operations layer (renamed from runner.py)
│                       #   Stable domain operations: returns frozen dataclasses
│                       #   Callable from CLI, flows, and dashboard
│                       #   May write artifacts within root-managed dirs only
│                       #   Never prints, never prompts, never logs to console
│                       #   Uses transactional writes (temp then rename)
├── context.py          # FlowContext + CaskCancelled exception
├── views/
│   ├── __init__.py
│   ├── tables.py       # Enhanced tool/approval/doctor tables
│   ├── diff.py         # Visual diff rendering (drift, plan, repair)
│   ├── status.py       # `cask status` builder
│   ├── progress.py     # Cancel-safe live progress (spinner/step/feed modes)
│   ├── branding.py     # Compact ASCII header (2 lines max, portal commands only)
│   └── next_steps.py   # Pure function: NextStepsInput → NextStepsOutput
├── flows/
│   ├── __init__.py     # Flow registry
│   ├── init.py         # Enhanced init wizard
│   ├── config.py       # Config flow (unchanged)
│   ├── doctor.py       # Doctor with progress
│   ├── repair.py       # 5-phase diagnostic + fix lifecycle
│   ├── gate_review.py  # PR-like risk-grouped approval
│   ├── gate_snapshot.py
│   ├── ship.py         # Flagship guided lifecycle (single Live context)
│   └── quickstart.py   # Enhanced onboarding
└── dashboard/          # Optional Textual (toolwright[tui])
    ├── __init__.py     # Graceful import fallback
    ├── app.py          # Read-only Textual App (calls ops.py)
    ├── widgets.py      # Custom widgets
    └── screens.py      # Dashboard screens
```

### Key Architectural Rules

1. **`ops.py`** — stable operations layer. Returns frozen dataclasses/Pydantic models. **Strict no-side-effects rule with one exception**: ops may write artifact files only within root-managed directories (`.toolwright/`). Ops never prints, never prompts, never logs to console. Uses transactional writes (temp dir then atomic rename). CLI, flows, and dashboard all call this. Defines: `get_status()`, `list_tools()`, `list_audit()`, `run_doctor_checks()`, `run_repair_preflight()`, `run_gate_approve()`, `run_gate_reject()`, `run_gate_snapshot()`.

2. **`FlowContext`** — single shared context threaded through all flows. Contains: root, toolpack_path, toolpack_id, toolpack_fingerprint, lockfile_path, capture_id, baseline_path, last_command, last_result, output_mode, intent, interactive.

3. **All Rich UI to stderr.** stdout only for machine output (`--json`), snippet emitters, and MCP protocol.

4. **Views expose three render functions**: `render_rich(data) -> Renderable`, `render_plain(data) -> str`, `render_json(data) -> dict`. Command picks one based on output_mode. Separate functions (not `if/else` inside a single function) to keep the boundary obvious.

5. **Dashboard** is read-only, toolpack-scoped, reads cached artifacts only (never runs drift/verify), calls `ops.py` for all data. Never implements logic that doesn't exist in CLI ops.

6. **Progress** is cancel-safe: catches `KeyboardInterrupt`, raises `CaskCancelled`, cleans up Live display, exit code 130. One implementation with three modes (spinner, step, feed). Operations write to temp dir, atomically rename on success.

7. **SymbolSet** — chosen once in `console.py` based on terminal capability. Rich mode uses Unicode if supported, else ASCII fallback. Plain mode is always ASCII-safe (no box drawing, no Unicode symbols, uses `*` `-` `[TAG]` prefixes). Respects `NO_COLOR` and `CLICOLOR=0`.

8. **Fingerprint function** — defined and stored. Inputs: toolpack.yaml contents, tools.json SHA, policy.yaml SHA, contracts.yaml SHA, approved lockfile SHA, baseline.json SHA (if present). Stored at `.toolwright/toolpacks/<id>/artifact/fingerprint.json`. Makes stage-skipping deterministic and testable.

### Dependency Strategy

- **Rich** (already required) — all CLI flow enhancements
- **prompt-toolkit** (add as required dep) — single-letter action prompts in fancy mode, cross-platform key handling
- **Textual** (optional: `toolwright[tui]`) — dashboard only
- If Textual not installed: `cask dashboard` prints install hint and shows `cask status` at appropriate output tier

### Output Tiers

| Tier | When | Behavior |
|------|------|----------|
| Rich Interactive | TTY stderr | Full colors, panels, tables, progress, Live displays, Unicode symbols (if terminal supports) |
| Rich Plain | non-TTY, `TERM=dumb`, `NO_COLOR`, `CLICOLOR=0` | ASCII-safe only: no box drawing, no Unicode, `[TAG]` prefixes, aligned columns without borders |
| JSON | `--json` flag | stdout: JSON only. stderr: only fatal errors and single-line warnings. Never render tables/progress to stderr. |
| Textual | `cask dashboard` | Full-screen app, graceful fallback to status at appropriate tier |

---

## Component Designs

### 1. `cask status` Command

The **compass** — always-available orientation point. Not a flow (no interactive sequence), just a command calling `views/status.py` + `views/next_steps.py`.

**Shows:**
- Root path + toolpack identity
- Lockfile state: sealed/pending/missing + approved/blocked counts
- Baseline state: current/stale/missing + when snapshot was taken
- Drift state: pass/warnings/breaking/not checked
- Verify state: pass/fail/not run + which modes
- Pending count + alerts (high-risk additions, broken verification)
- **"Next →"**: exactly one recommended action with command and explanation

**Status icons** (via SymbolSet):
- Rich mode: `✓` (good), `○` (unchecked), `✗` (failed), `!` (warning) — if terminal supports Unicode; else ASCII fallback
- Plain mode: `[OK]`, `[--]`, `[FAIL]`, `[WARN]`

### 2. Gate Review Flow (PR-Like Approval)

**Phase 1: Overview** — summary panel with total pending, risk breakdown, new capabilities

**Phase 2: Risk-Grouped Review** — highest risk first:
- **Critical & High**: reviewed individually with full context. Shows: tool name, method, path, host, **why it's risky** (human-readable explanation), scope.
  - Prompts: `[a]pprove  [b]lock  [s]kip  [d]iff  [y]why  [p]olicy  [?]help`
  - `[d]` opens diff viewer (pager) for the current tool — shows before/after if prior version exists
  - `[y]` shows expanded risk explanation with evidence
  - `[p]` shows which policy rule triggered the risk classification
  - Typed "APPROVE" confirmation for critical/high
- **Medium**: batch review. "Approve all N medium-risk tools? [Y/n] or [r]eview individually"
- **Low**: batch approve. "N low-risk read-only tools. Approve all? [Y/n]"

**Phase 3: Summary & Commit** — full decision table, commands to run, final confirmation

**UX details:**
- Single-letter shortcuts backed by prompt-toolkit in fancy mode (cross-platform), readline fallback in plain
- `q` exits cleanly with "No changes made"
- After approval shows "Next →"

### 3. Repair Flow (5-Phase Diagnostic + Fix Lifecycle)

**Phase 1: Repair Preflight** (fast, not full doctor) — only checks relevant to failure context:
- Missing lockfile/toolpack paths
- Permission issues
- Missing dependencies
- Full `doctor` remains available as `[D] full doctor` escape hatch

**Phase 2: Diagnosis** — human-readable explanations per issue (not codes), source attribution ("Detected from: audit log")

**Phase 3: Repair Plan** — patches grouped by safety:
- **Safe** (green): auto-applicable. Example: `cask gate sync`
- **Approval required** (yellow): need review. Example: `cask gate allow delete_user`
- **Manual** (red): can't automate. Example: "API endpoint removed — investigate upstream"

**Phase 4: Guided Resolution** — apply safe fixes with single confirmation + progress, dispatch to gate_review for approval-required, show guidance for manual

**Phase 5: Re-verify** — run verification with progress, show pass/fail, if fail: updated diagnosis. Never dead-ends.

### 4. Ship Flow (Flagship Guided Lifecycle)

**Stage tracker** (persistent, rendered via single `rich.live.Live` context owned by ship):
```
  capture ── review ── approve ── snapshot ── verify ── serve
    ✓          ✓         >>
```

**Stages:**
1. **Capture** — mint with progress, or use existing toolpack
2. **Review** — explicit preview vs diff fork:
   - If no prior baseline/toolpack: show **preview** (tool list + risk summary + policy summary). Message: "New toolpack. No prior baseline. Previewing generated surface."
   - If prior exists: show real **diff** via `views/diff.py`
3. **Approve** — dispatch to gate_review_flow. Skip if all approved.
4. **Snapshot** — auto-create baseline. Show path.
5. **Verify** — run with progress. If fail: offer jump to repair.
6. **Serve** — informational only. Print serve command + config snippet. Offer config_flow. Never starts a long-running process.

**Key rules:**
- **Ship owns exactly one Live context.** Sub-flows return renderables or "events", not their own Live instances. `ShipRenderer` holds: stage tracker renderable, current panel renderable, current progress renderable. Updated after each stage and key progress events.
- Stage completion is **fingerprint-based** (uses `fingerprint.json`):
  - capture: toolpack exists AND user chose "use existing"
  - review: diff report exists for current toolpack version OR user skipped
  - approve: approved lockfile exists AND pending_count == 0 AND lockfile fingerprint matches
  - snapshot: baseline artifact exists AND matches current approved lockfile fingerprint
  - verify: latest verify report exists AND is "pass" for current toolpack + lockfile version
  - serve: never "complete" (informational stage)
- Early exit (`q`, TTY only): prints completed stages, artifacts produced (paths), primary next step from NextStepsOutput
- Stage failure: short error summary → "what changed / why denied" → single best recovery action → never silently continue

### 5. Progress System (`views/progress.py`)

**API:**
```python
@contextmanager
def cask_progress(description: str, steps: list[str] | None = None) -> CaskProgress:
    # One implementation, three modes:
    # - Spinner: indeterminate (e.g., "Capturing browser traffic...")
    # - Step: n of m (e.g., "Compiling [2/5] Normalizing endpoints...")
    # - Feed: optional later (live discovery)
```

**Cancel safety:**
- Catches `KeyboardInterrupt`
- Cleans up Rich Live display
- Raises `CaskCancelled` (caught by top-level Click command)
- Exit code 130
- Does not leave partial state — operations write to temp dir, atomically rename on success

### 6. Diff View (`views/diff.py`)

**Stable categories** (locked, never new ones without version bump):
- BREAKING, AUTH, POLICY, SCHEMA, RISK, INFO

**Rich mode** — tree-style with severity icons (via SymbolSet):
```
  BREAKING  Endpoint removed: DELETE /api/admin/purge
  ├─ Risk: critical → (removed)
  ├─ Impact: Downstream flow broken
  └─ Action: Investigate
```

**Plain mode** — ASCII prefixed, no box drawing:
```
[BREAKING] Endpoint removed: DELETE /api/admin/purge
  Risk: critical -> (removed)
  Impact: Downstream flow broken
  Action: Investigate
```

**Summary footer:** change counts + exit code + "Next →"

### 7. Branding (`views/branding.py`)

Compact 2-line header, portal commands only (status, ship, demo, dashboard):
```
  cask v0.2.0  ·  governed agent tools
```
(Exact mark TBD — ASCII-safe in plain mode, can use a small Unicode mark in rich mode via SymbolSet)

Never pushes scrollback off-screen. Shows root path + toolpack path for multi-root awareness. Branding never appears inside subcommands (gate allow, drift, etc.) to keep CLI non-noisy.

### 8. FlowContext (`context.py`)

```python
@dataclass(frozen=True)
class FlowContext:
    root: Path
    toolpack_path: Path | None
    toolpack_id: str | None
    toolpack_fingerprint: str | None      # hash of key artifacts from fingerprint.json
    lockfile_path: Path | None
    capture_id: str | None
    baseline_path: Path | None
    last_command: str | None
    last_result: Any | None
    output_mode: Literal["rich", "plain", "json"]
    intent: str | None                    # "quickstart", "repair", "gate-review", "ship"
    interactive: bool

class CaskCancelled(Exception):
    """Raised on Ctrl-C during progress. Caught by top-level Click command."""
    pass
```

### 9. NextSteps (`views/next_steps.py`)

**Pure function.** No filesystem access. Takes `NextStepsInput`, returns `NextStepsOutput`.

```python
@dataclass(frozen=True)
class NextStepsInput:
    command: str
    toolpack_id: str | None
    lockfile_state: Literal["missing", "pending", "sealed", "stale"]
    verification_state: Literal["not_run", "pass", "fail", "partial"]
    drift_state: Literal["not_checked", "clean", "warnings", "breaking"]
    pending_count: int
    has_baseline: bool
    has_mcp_config: bool
    has_approved_lockfile: bool
    has_pending_lockfile: bool
    last_error_code: str | None
    environment: Literal["local", "ci", "container"]

@dataclass(frozen=True)
class NextStep:
    command: str       # e.g., "cask gate allow --toolpack stripe-api"
    label: str         # e.g., "Approve pending tools"
    why: str           # e.g., "2 tools awaiting approval before serving"

@dataclass(frozen=True)
class NextStepsOutput:
    primary: NextStep
    alternatives: list[NextStep]   # max 2-3
```

**Priority tree:**
1. Lockfile missing → `cask gate sync`
2. Pending tools → `cask gate allow`
3. Verification failed → `cask repair`
4. Drift breaking → investigate drift
5. No baseline → `cask gate snapshot`
6. No MCP config → `cask config`
7. Drift not checked → `cask drift`
8. All green → `cask serve`

### 10. Minimal Textual Dashboard

**Toolpack-scoped:** `cask dashboard --toolpack <path>` (interactive picker if missing in TTY)

**Read-only.** Only reads cached artifacts (toolpack + lockfile + last drift/verify reports). Never runs drift/verify. If reports are missing, shows "not run" state and the next recommended CLI command.

**Layout:**
1. **Header**: Cask branding + root path + toolpack ID
2. **Status grid**: lockfile state, drift state, verify state, pending count
3. **Tools DataTable**: sortable, filterable (`/`), columns: Status, Name, Risk, Method, Path, Host
4. **Recent audit**: last 10 decisions with timestamps
5. **Next action widget**: reuses NextStepsOutput — no new heuristics
6. **Footer**: keybinding hints (`q`=quit, `/`=filter, `r`=refresh, `?`=help)

**Refresh**: safe and fast — reads cached artifacts only, no heavy computation.

**Fallback:** If Textual not installed, print install hint and show `cask status` at the appropriate output tier (rich or plain depending on TTY/env).

### 11. Enhanced Prompts (`prompts.py`)

Keep existing primitives, enhance:
- Add `prompt_action()` for single-letter action selection:
  - Fancy mode: uses prompt-toolkit key bindings (cross-platform, handles arrow keys)
  - Plain mode: falls back to `input_stream` / readline
- Single-letter keyboard hint display: `[a]pprove  [b]lock  [s]kip`
- Style prompts with Rich markup
- Keep all prompts testable via `input_stream` parameter

### 12. Enhanced Console Theme & SymbolSet (`console.py`)

**SymbolSet**: chosen once based on terminal capability detection.

```python
@dataclass(frozen=True)
class SymbolSet:
    ok: str          # ✓ or [OK]
    fail: str        # ✗ or [FAIL]
    pending: str     # ○ or [--]
    warning: str     # ! or [WARN]
    arrow: str       # → or ->
    branch: str      # ├─ or |-
    corner: str      # └─ or \-
    active: str      # >> or >>
```

**Expanded CASK_THEME:**
```python
"seal": "bold green",
"drift.breaking": "bold red",
"drift.auth": "red",
"drift.policy": "yellow",
"drift.schema": "cyan",
"drift.risk": "yellow",
"drift.info": "dim",
"tool.read": "green",
"tool.write": "yellow",
"tool.delete": "red",
"audit.who": "bold",
"audit.when": "dim",
"next": "bold cyan",
```

---

## Ops Layer Contract (`ops.py`)

Stable functions returning serializable models. **Strict rules**: never prints, never prompts, never logs to console. May write artifacts only within `.toolwright/` root-managed directories using transactional writes.

```python
def get_status(toolpack_path: Path) -> StatusModel: ...
def list_tools(toolpack_path: Path) -> list[ToolModel]: ...
def list_audit(toolpack_path: Path, limit: int = 10) -> list[AuditEvent]: ...
def run_doctor_checks(toolpack_path: Path, runtime: str = "auto") -> DoctorResult: ...
def run_repair_preflight(toolpack_path: Path) -> PreflightResult: ...
def run_gate_approve(tool_ids: list[str], lockfile_path: Path, ...) -> ApproveResult: ...
def run_gate_reject(tool_ids: list[str], lockfile_path: Path, ...) -> list[str]: ...
def run_gate_snapshot(lockfile_path: Path) -> Path: ...
def load_lockfile_tools(lockfile_path: Path) -> tuple[Lockfile, list[ToolApproval]]: ...
def compute_fingerprint(toolpack_path: Path) -> str: ...
```

All return frozen dataclasses or Pydantic models. Serializable for JSON mode.

---

## Implementation Order

### Phase 1: Foundation (do first, everything else depends on it)
1. `context.py` — FlowContext + CaskCancelled exception
2. `views/next_steps.py` — pure NextSteps function with tests
3. `ops.py` — rename runner.py, add `get_status()`, `run_repair_preflight()`, `compute_fingerprint()`, keep existing ops. Enforce transactional write pattern.
4. `console.py` — expand theme palette + SymbolSet with capability detection
5. `views/branding.py` — compact header (SymbolSet-aware)
6. `views/progress.py` — cancel-safe progress (spinner + step modes)

### Phase 2: Core Views
7. `views/status.py` — status builder with render_rich/render_plain/render_json
8. `views/tables.py` — enhance existing tables, add risk explanations, risk grouping
9. `views/diff.py` — drift/plan diff rendering with stable categories, plain fallback
10. `cask status` command — wire up views/status + views/next_steps in `cli/main.py`

### Phase 3: Enhanced Flows
11. `prompts.py` — add `prompt_action()` with prompt-toolkit in fancy mode, readline fallback
12. `flows/gate_review.py` — PR-like risk-grouped approval with `[d]iff [y]why [p]olicy` escape hatches
13. `flows/repair.py` — 5-phase lifecycle (preflight, not full doctor in Phase 1)
14. `flows/ship.py` — guided lifecycle with single Live context, ShipRenderer, stage tracker, fingerprint-based idempotency

### Phase 4: Dashboard & Polish
15. `dashboard/` — minimal Textual dashboard (read-only, toolpack-scoped, calls ops.py)
16. `--json` output mode across all commands (views already have render_json)
17. Shell completions (Click built-in)
18. Update demos (cask-studio screenplays) to match new TUI output
19. `pyproject.toml` — add prompt-toolkit to deps, Textual to `[tui]` optional dep

---

## Critical Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `toolwright/ui/runner.py` | Rename to `ops.py`, expand | Stable operations layer with strict side-effect rules |
| `toolwright/ui/console.py` | Expand theme + add SymbolSet | New semantic colors, Unicode/ASCII capability detection |
| `toolwright/ui/prompts.py` | Enhance + add prompt_action() | prompt-toolkit backed single-letter actions |
| `toolwright/ui/tables.py` | Move to `views/tables.py`, enhance | Risk explanations, grouping, SymbolSet-aware |
| `toolwright/ui/flows/gate_review.py` | Rewrite | PR-like risk-grouped approval with diff/why/policy escape hatches |
| `toolwright/ui/flows/repair.py` | Rewrite | 5-phase lifecycle, preflight instead of full doctor |
| `toolwright/ui/flows/ship.py` | Rewrite | Single Live context, ShipRenderer, fingerprint-based stages |
| `toolwright/ui/flows/__init__.py` | Update | New flow registrations |
| `toolwright/cli/main.py` | Add `status` + `dashboard` commands | New commands wired to views |
| `toolwright/ui/context.py` | New | FlowContext + CaskCancelled |
| `toolwright/ui/views/*.py` | New | All view modules (6 files) |
| `toolwright/ui/dashboard/*.py` | New | Textual dashboard (4 files) |
| `pyproject.toml` | Add deps | prompt-toolkit required, Textual in `[tui]` |
| `cask-studio/screenplays/*.yaml` | Update | Match new TUI output |

---

## Verification Plan

1. **Unit tests**: Pure functions (next_steps, status builder, diff view, compute_fingerprint) have full test coverage
2. **Integration tests**: Each flow tested with `input_stream` injection via prompt primitives
3. **Plain mode tests**: Verify ASCII-safe output — no Unicode, no box drawing, no color codes
4. **JSON mode tests**: Verify valid JSON to stdout, stderr has only fatal errors / single-line warnings
5. **Cancel tests**: Verify Ctrl-C raises CaskCancelled, returns exit code 130, no partial state (temp files cleaned)
6. **Fingerprint tests**: Verify deterministic fingerprinting, stage-skip correctness
7. **SymbolSet tests**: Verify ASCII fallback when terminal doesn't support Unicode
8. **Cross-platform**: Test on macOS + Linux. Plain mode verified on Windows terminal.
9. **Visual verification**: Run each command manually, compare output against design
10. **Demo verification**: Re-record cask-studio screenplays, verify 1:1 with actual output
11. **Lint/typecheck**: `ruff check`, `mypy` pass
12. **Existing tests**: `python -m pytest tests/ -v` all pass — no regressions
