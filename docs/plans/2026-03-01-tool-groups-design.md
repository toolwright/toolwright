# Tool Groups, Serve-Time Scoping, and Tool Count Guardrails

**Date:** 2026-03-01
**Status:** Design

## Problem

Large OpenAPI specs (Shopify: 1183 tools, GitHub: 1048) cause:
1. **Agent failure** — LLMs degrade above 30 tools, fail above 100
2. **Governance failure** — Nobody reviews 1183 tools; everyone runs `gate allow --all`
3. **UX failure** — Wall of tools with no structure

## Solution Overview

Three backward-compatible changes:
1. Auto-generate tool groups at compile time from URL path structure
2. Add `--scope` flag to `serve` to filter tools by group
3. Warn/block at serve time when tool count exceeds safe thresholds

---

## 1. Data Model

### New file: `toolwright/models/groups.py`

```python
@dataclass
class ToolGroup:
    name: str              # "products", "repos/issues"
    tools: list[str]       # tool IDs (action names)
    path_prefix: str       # "/admin/api/*/products"
    description: str | None

@dataclass
class ToolGroupIndex:
    groups: list[ToolGroup]
    ungrouped: list[str]
    generated_from: str    # "auto" or "manual"
```

### Toolpack model changes

`ToolpackPaths` gets `groups: str | None = None` (relative path to groups.json).
`ResolvedToolpackPaths` gets `groups_path: Path | None = None`.

---

## 2. Grouping Algorithm

### New file: `toolwright/core/compile/grouper.py`

**Input:** List of action dicts from tools.json (each has `name`, `path`, `host`, `method`)

**Steps:**

1. **Extract and clean path** — Strip noise segments (`admin`, `api`, `rest`, version patterns like `v1`/`2026-01`, path params `{...}`, file extensions `.json`/`.xml`)
2. **Assign primary group** — First semantic segment (lowercased)
3. **Auto-split large groups** — If group > 80 tools, split by second segment. Recurse up to depth 3.
4. **Generate descriptions** — `"Products endpoints (23 tools)"`
5. **Sort and output** — Alphabetical groups, alphabetical tools within each

**Noise patterns:**
```python
NOISE_PATTERNS = [
    r"^admin$", r"^api$", r"^rest$",
    r"^v\d+$", r"^\d{4}-\d{2}$",
    r"^unstable$", r"^stable$", r"^latest$",
]
```

---

## 3. Compile Pipeline Integration

### `toolwright/cli/compile.py` — `compile_capture_session()`

After tools.json is written (~line 220), call grouper:
```python
from toolwright.core.compile.grouper import generate_tool_groups
groups_index = generate_tool_groups(manifest["actions"])
# Write groups.json alongside tools.json
```

`CompileResult` gets `groups_path: Path | None`.

### `toolwright/cli/mint.py` — `run_mint()`

After artifacts are copied to toolpack dir, groups.json is already in the artifact directory. Update `ToolpackPaths` to include `groups` field pointing to it.

### Post-compile output

Print group summary after compile:
```
Compiled 1183 tools in 47 groups
  products (23)    orders (31)    customers (18)    themes (15)
  ...
  Serve subset: toolwright serve --scope products,orders
  All groups:  toolwright groups list
```

---

## 4. `--scope` on serve

### `toolwright/cli/commands_mcp.py`

New options:
- `--scope / -s` — Comma-separated group names
- `--no-tool-limit` — Override 200-tool hard block

### `toolwright/cli/mcp.py` — `run_mcp_serve()`

New params: `scope: str | None`, `no_tool_limit: bool`.

Filter chain (AND logic):
```
tools → filter_by_scope → filter_by_toolset → filter_by_risk → filter_by_glob
```

Scope filtering happens before `ToolwrightMCPServer` construction.

**Prefix matching:** `--scope repos` matches `repos`, `repos/issues`, `repos/pulls`.

**Error handling:**
- Unknown group name → error with "did you mean?" (Levenshtein ≤ 2)
- No groups.json → warning, serves all tools

---

## 5. Tool Count Guardrails

**Constants:**
```python
TOOL_COUNT_WARN_THRESHOLD = 30
TOOL_COUNT_BLOCK_THRESHOLD = 200
```

**In `run_mcp_serve()` after all filtering:**
- 31–200 tools: warning to stderr with group suggestions, server starts
- 201+ tools: error with group suggestions, server does NOT start (unless `--no-tool-limit`)

---

## 6. CLI Commands

### New file: `toolwright/cli/commands_groups.py`

**`toolwright groups list`** — Lists all groups with tool counts and descriptions.
**`toolwright groups show <name>`** — Lists tools in a group with method/path.

Register as a command group in `main.py`.

---

## 7. Gate Integration

### `toolwright/cli/commands_approval.py`

- `gate allow --scope <groups>` — Approve all tools in named groups
- `gate block --scope <groups>` — Block all tools in named groups
- `gate status --by-group` — Per-group approval summary
- `gate status --scope <group>` — Drill into specific group

---

## 8. Startup Card

### `toolwright/mcp/startup_card.py`

When `--scope` active:
```
Tools: 54 (scope: products, orders) of 1183 compiled
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `toolwright/models/groups.py` | ToolGroup, ToolGroupIndex dataclasses |
| `toolwright/core/compile/grouper.py` | Grouping algorithm |
| `toolwright/cli/commands_groups.py` | `groups list`, `groups show` CLI |
| `tests/test_grouper.py` | Grouping algorithm unit tests |
| `tests/test_groups_cli.py` | CLI integration tests |
| `tests/test_serve_scope.py` | Scope filtering + guardrails tests |

## Files to Modify

| File | Change |
|------|--------|
| `toolwright/core/toolpack.py` | Add `groups` to ToolpackPaths + ResolvedToolpackPaths |
| `toolwright/cli/compile.py` | Call grouper after tools.json, add groups_path to CompileResult |
| `toolwright/cli/mint.py` | Include groups in toolpack packaging |
| `toolwright/cli/commands_mcp.py` | Add `--scope`, `--no-tool-limit` options |
| `toolwright/cli/mcp.py` | Scope filtering + guardrails logic |
| `toolwright/mcp/startup_card.py` | Show scope info |
| `toolwright/cli/commands_approval.py` | `--scope` on allow/block, `--by-group` on status |
| `toolwright/cli/main.py` | Register groups command group |

## Out of Scope (Deferred)

- Manual group editing (move/create/regenerate)
- Progressive tool discovery (meta-tools)
- Recipe-defined scopes
- Per-group behavioral rules
- Group-aware drift detection
