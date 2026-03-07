# Tool Groups Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Auto-generate tool groups from URL path structure at compile time, add `--scope` to `serve` for group-based filtering, and add tool count guardrails that warn/block when serving too many tools.

**Architecture:** The grouper runs as a post-compile step after tools.json is written, producing groups.json alongside it. Scope filtering happens in `run_mcp_serve()` before `ToolwrightMCPServer` is constructed, using the same pattern as existing `tool_filter`/`max_risk` filtering. Groups are stored as a new `ToolpackPaths.groups` field and resolved via `ResolvedToolpackPaths.groups_path`.

**Tech Stack:** Python 3.11+, Click CLI, dataclasses (not Pydantic) for group models, pytest for tests.

---

### Task 1: Data Model — ToolGroup and ToolGroupIndex

**Files:**
- Create: `toolwright/models/groups.py`
- Test: `tests/test_grouper.py`

**Step 1: Write the failing test for serialization round-trip**

Create `tests/test_grouper.py`:

```python
"""Tests for tool grouping algorithm and data model."""
from __future__ import annotations

import json

from toolwright.models.groups import ToolGroup, ToolGroupIndex


def test_tool_group_index_to_dict():
    """ToolGroupIndex serializes to the expected JSON structure."""
    index = ToolGroupIndex(
        groups=[
            ToolGroup(
                name="products",
                tools=["get_products", "create_product"],
                path_prefix="/admin/api/*/products",
                description="Products endpoints (2 tools)",
            ),
        ],
        ungrouped=["orphan_tool"],
        generated_from="auto",
    )
    data = index.to_dict()
    assert data["generated_from"] == "auto"
    assert len(data["groups"]) == 1
    assert data["groups"][0]["name"] == "products"
    assert data["groups"][0]["tools"] == ["get_products", "create_product"]
    assert data["ungrouped"] == ["orphan_tool"]


def test_tool_group_index_from_dict():
    """ToolGroupIndex deserializes from JSON dict."""
    data = {
        "groups": [
            {
                "name": "products",
                "tools": ["get_products"],
                "path_prefix": "/products",
                "description": "Products endpoints (1 tools)",
            },
        ],
        "ungrouped": [],
        "generated_from": "auto",
    }
    index = ToolGroupIndex.from_dict(data)
    assert len(index.groups) == 1
    assert index.groups[0].name == "products"
    assert index.generated_from == "auto"


def test_tool_group_index_json_round_trip():
    """ToolGroupIndex round-trips through JSON."""
    index = ToolGroupIndex(
        groups=[
            ToolGroup(
                name="orders",
                tools=["get_orders"],
                path_prefix="/orders",
                description="Orders endpoints (1 tools)",
            ),
        ],
        ungrouped=["misc"],
        generated_from="auto",
    )
    json_str = json.dumps(index.to_dict())
    restored = ToolGroupIndex.from_dict(json.loads(json_str))
    assert restored.groups[0].name == "orders"
    assert restored.ungrouped == ["misc"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_grouper.py -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'toolwright.models.groups'`

**Step 3: Write minimal implementation**

Create `toolwright/models/groups.py`:

```python
"""Tool group data model for organizing tools by URL resource."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolGroup:
    """A named group of tools sharing a URL resource prefix."""

    name: str
    tools: list[str]
    path_prefix: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tools": self.tools,
            "path_prefix": self.path_prefix,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolGroup:
        return cls(
            name=data["name"],
            tools=data["tools"],
            path_prefix=data["path_prefix"],
            description=data.get("description"),
        )


@dataclass
class ToolGroupIndex:
    """Top-level container written to groups.json."""

    groups: list[ToolGroup] = field(default_factory=list)
    ungrouped: list[str] = field(default_factory=list)
    generated_from: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "ungrouped": self.ungrouped,
            "generated_from": self.generated_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolGroupIndex:
        groups = [ToolGroup.from_dict(g) for g in data.get("groups", [])]
        return cls(
            groups=groups,
            ungrouped=data.get("ungrouped", []),
            generated_from=data.get("generated_from", "auto"),
        )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_grouper.py -v -x`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add toolwright/models/groups.py tests/test_grouper.py
git commit -m "feat: add ToolGroup and ToolGroupIndex data model"
```

---

### Task 2: Grouping Algorithm — Path Cleaning

**Files:**
- Create: `toolwright/core/compile/grouper.py`
- Modify: `tests/test_grouper.py`

**Step 1: Write failing tests for path cleaning**

Append to `tests/test_grouper.py`:

```python
from toolwright.core.compile.grouper import extract_semantic_segments


def test_strips_admin_api_version():
    """Strips admin, api, version segments."""
    assert extract_semantic_segments("/admin/api/2026-01/products/{id}") == ["products"]


def test_strips_v_prefix():
    """Strips v1/v2/v3 segments."""
    assert extract_semantic_segments("/v2/users/{id}/posts") == ["users", "posts"]


def test_strips_path_params():
    """Strips path parameters like {owner}, {repo}."""
    assert extract_semantic_segments("/repos/{owner}/{repo}/issues") == ["repos", "issues"]


def test_strips_file_extensions():
    """Strips .json/.xml/.yaml from last segment."""
    assert extract_semantic_segments("/products.json") == ["products"]


def test_strips_express_params():
    """Strips Express-style :id parameters."""
    assert extract_semantic_segments("/users/:id/posts") == ["users", "posts"]


def test_empty_after_cleaning():
    """Path with only params returns empty list."""
    assert extract_semantic_segments("/{id}") == []


def test_preserves_meaningful_segments():
    """Non-noise segments are preserved."""
    assert extract_semantic_segments("/users/search") == ["users", "search"]


def test_case_insensitive_noise():
    """Noise patterns are case-insensitive."""
    assert extract_semantic_segments("/Admin/API/v2/Products") == ["products"]
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_grouper.py -v -x`
Expected: FAIL — `ImportError: cannot import name 'extract_semantic_segments'`

**Step 3: Write implementation**

Create `toolwright/core/compile/grouper.py`:

```python
"""Auto-generate tool groups from URL path structure.

Groups tools by their primary URL resource segment after stripping
noise (api versions, admin prefixes, path parameters, file extensions).
Large groups are auto-split by secondary segments.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from toolwright.models.groups import ToolGroup, ToolGroupIndex

# Segments that carry no resource semantics
NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^admin$", re.IGNORECASE),
    re.compile(r"^api$", re.IGNORECASE),
    re.compile(r"^rest$", re.IGNORECASE),
    re.compile(r"^v\d+$", re.IGNORECASE),
    re.compile(r"^\d{4}-\d{2}$"),  # 2026-01
    re.compile(r"^unstable$", re.IGNORECASE),
    re.compile(r"^stable$", re.IGNORECASE),
    re.compile(r"^latest$", re.IGNORECASE),
]

# File extensions to strip from the last segment
_EXT_RE = re.compile(r"\.(json|xml|yaml)$", re.IGNORECASE)

AUTO_SPLIT_THRESHOLD = 80
MAX_SPLIT_DEPTH = 3


def _is_noise(segment: str) -> bool:
    """Return True if segment matches any noise pattern."""
    return any(p.match(segment) for p in NOISE_PATTERNS)


def _is_path_param(segment: str) -> bool:
    """Return True for path parameter segments like {id} or :id."""
    return segment.startswith("{") or segment.startswith(":")


def extract_semantic_segments(path: str) -> list[str]:
    """Extract meaningful resource segments from a URL path.

    Strips noise prefixes (admin, api, versions), path parameters,
    and file extensions.
    """
    raw_segments = [s for s in path.strip("/").split("/") if s]

    # Strip file extension from last segment
    if raw_segments:
        raw_segments[-1] = _EXT_RE.sub("", raw_segments[-1])
        if not raw_segments[-1]:
            raw_segments.pop()

    segments: list[str] = []
    for seg in raw_segments:
        if _is_path_param(seg):
            continue
        if _is_noise(seg):
            continue
        segments.append(seg.lower())

    return segments
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_grouper.py -v -x`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add toolwright/core/compile/grouper.py tests/test_grouper.py
git commit -m "feat: add path cleaning for tool grouping algorithm"
```

---

### Task 3: Grouping Algorithm — Primary Grouping and Auto-Split

**Files:**
- Modify: `toolwright/core/compile/grouper.py`
- Modify: `tests/test_grouper.py`

**Step 1: Write failing tests for grouping**

Append to `tests/test_grouper.py`:

```python
from toolwright.core.compile.grouper import generate_tool_groups


def _make_action(name: str, path: str) -> dict[str, Any]:
    """Helper to create a minimal action dict."""
    return {"name": name, "path": path, "method": "GET", "host": "api.example.com"}


def test_groups_by_first_segment():
    """Tools with /products/... all land in 'products' group."""
    actions = [
        _make_action("get_products", "/admin/api/2026-01/products.json"),
        _make_action("get_product", "/admin/api/2026-01/products/{id}.json"),
        _make_action("create_product", "/admin/api/2026-01/products.json"),
    ]
    index = generate_tool_groups(actions)
    names = {g.name for g in index.groups}
    assert "products" in names
    products_group = next(g for g in index.groups if g.name == "products")
    assert sorted(products_group.tools) == ["create_product", "get_product", "get_products"]


def test_different_paths_different_groups():
    """Different resource paths produce different groups."""
    actions = [
        _make_action("get_products", "/products"),
        _make_action("get_orders", "/orders"),
    ]
    index = generate_tool_groups(actions)
    names = sorted(g.name for g in index.groups)
    assert names == ["orders", "products"]


def test_sub_resources_stay_in_parent():
    """/products/{id}/images stays in 'products' group."""
    actions = [
        _make_action("get_product_images", "/products/{id}/images"),
    ]
    index = generate_tool_groups(actions)
    assert len(index.groups) == 1
    assert index.groups[0].name == "products"


def test_no_tools_empty_output():
    """Empty action list produces empty index."""
    index = generate_tool_groups([])
    assert index.groups == []
    assert index.ungrouped == []


def test_single_tool():
    """One tool produces one group."""
    actions = [_make_action("get_user", "/users/{id}")]
    index = generate_tool_groups(actions)
    assert len(index.groups) == 1
    assert index.groups[0].tools == ["get_user"]


def test_ungrouped_when_no_segments():
    """Tool with only params goes to ungrouped."""
    actions = [_make_action("get_root", "/{id}")]
    index = generate_tool_groups(actions)
    assert index.ungrouped == ["get_root"]


def test_auto_splits_large_group():
    """Group exceeding threshold splits by second segment."""
    actions = []
    for i in range(100):
        actions.append(_make_action(f"get_repo_issue_{i}", f"/repos/{{owner}}/{{repo}}/issues/{i}"))
    for i in range(100):
        actions.append(_make_action(f"get_repo_pull_{i}", f"/repos/{{owner}}/{{repo}}/pulls/{i}"))
    index = generate_tool_groups(actions)
    names = {g.name for g in index.groups}
    assert "repos/issues" in names
    assert "repos/pulls" in names


def test_no_split_below_threshold():
    """Group with fewer than threshold tools stays intact."""
    actions = [_make_action(f"get_product_{i}", f"/products/{i}") for i in range(50)]
    index = generate_tool_groups(actions)
    names = [g.name for g in index.groups]
    assert names == ["products"]


def test_split_produces_catch_all():
    """After split, tools without second segment remain in parent."""
    actions = []
    # 90 tools with second segment "issues"
    for i in range(90):
        actions.append(_make_action(f"issue_{i}", f"/repos/{{owner}}/{{repo}}/issues/{i}"))
    # 5 tools at top-level /repos
    for i in range(5):
        actions.append(_make_action(f"repo_{i}", f"/repos/{{owner}}/{{repo}}"))
    index = generate_tool_groups(actions)
    names = {g.name for g in index.groups}
    assert "repos/issues" in names
    assert "repos" in names  # catch-all for top-level
    repos_group = next(g for g in index.groups if g.name == "repos")
    assert len(repos_group.tools) == 5


def test_description_generated():
    """Groups get auto-generated descriptions."""
    actions = [_make_action("get_products", "/products")]
    index = generate_tool_groups(actions)
    assert index.groups[0].description == "Products endpoints (1 tools)"


def test_groups_sorted_alphabetically():
    """Groups are sorted alphabetically by name."""
    actions = [
        _make_action("get_z", "/zebras"),
        _make_action("get_a", "/apples"),
        _make_action("get_m", "/mangos"),
    ]
    index = generate_tool_groups(actions)
    names = [g.name for g in index.groups]
    assert names == ["apples", "mangos", "zebras"]


def test_tools_sorted_within_group():
    """Tools within a group are sorted alphabetically."""
    actions = [
        _make_action("delete_product", "/products/{id}"),
        _make_action("create_product", "/products"),
        _make_action("get_products", "/products"),
    ]
    index = generate_tool_groups(actions)
    assert index.groups[0].tools == ["create_product", "delete_product", "get_products"]
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_grouper.py::test_groups_by_first_segment -v -x`
Expected: FAIL — `ImportError: cannot import name 'generate_tool_groups'`

**Step 3: Write implementation**

Add to `toolwright/core/compile/grouper.py`:

```python
def _build_path_prefix(group_name: str) -> str:
    """Reconstruct a human-readable path prefix from a group name."""
    parts = group_name.split("/")
    return "/" + "/".join(f"*/{p}" if i > 0 else p for i, p in enumerate(parts))


def _generate_description(group_name: str, tool_count: int) -> str:
    """Generate a human-readable group description."""
    label = group_name.replace("/", " \u203a ").title()
    return f"{label} endpoints ({tool_count} tools)"


def _split_group(
    group_name: str,
    tools_with_segments: list[tuple[str, list[str]]],
    depth: int,
) -> list[ToolGroup]:
    """Recursively split a large group by the next semantic segment.

    Args:
        group_name: Current group name (e.g., "repos")
        tools_with_segments: List of (tool_name, remaining_segments) pairs
        depth: Current split depth (max MAX_SPLIT_DEPTH)
    """
    if depth >= MAX_SPLIT_DEPTH or len(tools_with_segments) <= AUTO_SPLIT_THRESHOLD:
        tools = sorted(name for name, _ in tools_with_segments)
        return [
            ToolGroup(
                name=group_name,
                tools=tools,
                path_prefix=_build_path_prefix(group_name),
                description=_generate_description(group_name, len(tools)),
            )
        ]

    # Split by next segment
    sub_groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    catch_all: list[tuple[str, list[str]]] = []

    for tool_name, segments in tools_with_segments:
        if segments:
            sub_key = segments[0]
            sub_groups[sub_key].append((tool_name, segments[1:]))
        else:
            catch_all.append((tool_name, []))

    # If splitting doesn't help (all same sub-key), stop
    if len(sub_groups) <= 1 and not catch_all:
        tools = sorted(name for name, _ in tools_with_segments)
        return [
            ToolGroup(
                name=group_name,
                tools=tools,
                path_prefix=_build_path_prefix(group_name),
                description=_generate_description(group_name, len(tools)),
            )
        ]

    result: list[ToolGroup] = []

    # Recurse into sub-groups
    for sub_key in sorted(sub_groups):
        sub_name = f"{group_name}/{sub_key}"
        result.extend(
            _split_group(sub_name, sub_groups[sub_key], depth + 1)
        )

    # Catch-all: tools with no further segments stay in parent
    if catch_all:
        tools = sorted(name for name, _ in catch_all)
        result.append(
            ToolGroup(
                name=group_name,
                tools=tools,
                path_prefix=_build_path_prefix(group_name),
                description=_generate_description(group_name, len(tools)),
            )
        )

    return result


def generate_tool_groups(actions: list[dict[str, Any]]) -> ToolGroupIndex:
    """Generate a ToolGroupIndex from compiled tool actions.

    Each action must have 'name' and 'path' fields.
    Groups tools by the first semantic URL segment, then auto-splits
    large groups by secondary segments.
    """
    # Phase 1: Assign primary group
    primary_groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    ungrouped: list[str] = []

    for action in actions:
        name = action["name"]
        path = action.get("path", "/")
        segments = extract_semantic_segments(path)

        if not segments:
            ungrouped.append(name)
            continue

        primary = segments[0]
        remaining = segments[1:]
        primary_groups[primary].append((name, remaining))

    # Phase 2: Auto-split large groups
    all_groups: list[ToolGroup] = []
    for group_name in sorted(primary_groups):
        tools_with_segments = primary_groups[group_name]
        all_groups.extend(
            _split_group(group_name, tools_with_segments, depth=0)
        )

    # Sort groups alphabetically
    all_groups.sort(key=lambda g: g.name)

    return ToolGroupIndex(
        groups=all_groups,
        ungrouped=sorted(ungrouped),
        generated_from="auto",
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_grouper.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add toolwright/core/compile/grouper.py tests/test_grouper.py
git commit -m "feat: add tool grouping algorithm with auto-split"
```

---

### Task 4: Toolpack Model — Add groups field

**Files:**
- Modify: `toolwright/core/toolpack.py`

**Step 1: Write failing test**

Append to `tests/test_grouper.py`:

```python
from toolwright.core.toolpack import ToolpackPaths


def test_toolpack_paths_has_groups_field():
    """ToolpackPaths accepts and stores groups field."""
    paths = ToolpackPaths(
        tools="artifact/tools.json",
        toolsets="artifact/toolsets.yaml",
        policy="artifact/policy.yaml",
        baseline="artifact/baseline.json",
        groups="artifact/groups.json",
    )
    assert paths.groups == "artifact/groups.json"


def test_toolpack_paths_groups_defaults_none():
    """ToolpackPaths.groups defaults to None."""
    paths = ToolpackPaths(
        tools="artifact/tools.json",
        toolsets="artifact/toolsets.yaml",
        policy="artifact/policy.yaml",
        baseline="artifact/baseline.json",
    )
    assert paths.groups is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_grouper.py::test_toolpack_paths_has_groups_field -v -x`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'groups'`

**Step 3: Modify `toolwright/core/toolpack.py`**

Add `groups` field to `ToolpackPaths` (after `evidence_summary_sha256`):

```python
groups: str | None = None
```

Add `groups_path` to `ResolvedToolpackPaths` (after `evidence_summary_sha256_path`):

```python
groups_path: Path | None
```

In `resolve_toolpack_paths()`, add resolution for groups:

```python
groups_path=_resolve(toolpack.paths.groups),
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_grouper.py::test_toolpack_paths_has_groups_field tests/test_grouper.py::test_toolpack_paths_groups_defaults_none -v`
Expected: PASS

**Step 5: Verify existing tests still pass**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -5`
Expected: All existing tests pass (the new field has a default of None so it's backward-compatible)

**Step 6: Commit**

```bash
git add toolwright/core/toolpack.py tests/test_grouper.py
git commit -m "feat: add groups field to ToolpackPaths and ResolvedToolpackPaths"
```

---

### Task 5: Compile Pipeline — Generate groups.json

**Files:**
- Modify: `toolwright/cli/compile.py`
- Modify: `tests/test_grouper.py`

**Step 1: Write failing test**

Append to `tests/test_grouper.py`:

```python
import json as json_mod
from pathlib import Path


def test_groups_json_written_during_compile(tmp_path: Path):
    """compile_capture_session writes groups.json alongside tools.json."""
    from toolwright.cli.compile import compile_capture_session
    from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod

    session = CaptureSession(
        id="test-session",
        name="Test",
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/products",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/products",
                request_headers={},
                response_status=200,
                response_headers={"content-type": "application/json"},
                response_body_json={"id": 1},
            ),
            HttpExchange(
                url="https://api.example.com/orders",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/orders",
                request_headers={},
                response_status=200,
                response_headers={"content-type": "application/json"},
                response_body_json={"id": 1},
            ),
        ],
    )

    result = compile_capture_session(
        session=session,
        scope_name="default",
        scope_file=None,
        output_format="all",
        output_dir=tmp_path,
        deterministic=True,
    )

    assert result.groups_path is not None
    assert result.groups_path.exists()

    with open(result.groups_path) as f:
        data = json_mod.load(f)
    assert "groups" in data
    assert data["generated_from"] == "auto"
    group_names = {g["name"] for g in data["groups"]}
    assert "products" in group_names or "orders" in group_names
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_grouper.py::test_groups_json_written_during_compile -v -x`
Expected: FAIL — `AttributeError: 'CompileResult' object has no attribute 'groups_path'` (or groups_path is None)

**Step 3: Modify `toolwright/cli/compile.py`**

In `CompileResult` dataclass, add after `baseline_path`:

```python
groups_path: Path | None = None
```

In `compile_capture_session()`, after tools.json is written (around line 220, after `artifacts_created.append(("Tool Manifest", tools_path))`), add:

```python
        # Generate tool groups from compiled actions
        from toolwright.core.compile.grouper import generate_tool_groups

        groups_index = generate_tool_groups(manifest.get("actions", []))
        groups_path = output_path / "groups.json"
        with open(groups_path, "w") as f:
            json.dump(groups_index.to_dict(), f, indent=2)
        artifacts_created.append(("Tool Groups", groups_path))
```

Initialize `groups_path` variable at the top of the function alongside the others:

```python
groups_path: Path | None = None
```

Add `groups_path=groups_path` to the `CompileResult(...)` return at the bottom.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_grouper.py::test_groups_json_written_during_compile -v -x`
Expected: PASS

**Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 6: Commit**

```bash
git add toolwright/cli/compile.py tests/test_grouper.py
git commit -m "feat: generate groups.json in compile pipeline"
```

---

### Task 6: Mint Pipeline — Include groups.json in Toolpack

**Files:**
- Modify: `toolwright/cli/mint.py`
- Modify: `toolwright/cli/compile.py` (the `_package_toolpack` function)

**Step 1: Modify `_package_toolpack` in `compile.py`**

After `copied_baseline`, add:

```python
copied_groups = artifact_dir / "groups.json"
```

In the `ToolpackPaths(...)` constructor, add:

```python
groups=(
    str(copied_groups.relative_to(toolpack_dir))
    if copied_groups.exists()
    else None
),
```

**Step 2: Modify `run_mint` in `mint.py`**

Similarly, after `copied_baseline` line, add:

```python
copied_groups = artifact_dir / "groups.json"
```

In the `ToolpackPaths(...)` constructor (around line 307), add the same `groups` field:

```python
groups=(
    str(copied_groups.relative_to(toolpack_dir))
    if copied_groups.exists()
    else None
),
```

**Step 3: Run existing tests**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 4: Commit**

```bash
git add toolwright/cli/mint.py toolwright/cli/compile.py
git commit -m "feat: include groups.json in toolpack packaging"
```

---

### Task 7: Scope Filtering — `filter_by_scope` Function

**Files:**
- Modify: `toolwright/core/compile/grouper.py`
- Create: `tests/test_serve_scope.py`

**Step 1: Write failing tests**

Create `tests/test_serve_scope.py`:

```python
"""Tests for --scope filtering and tool count guardrails."""
from __future__ import annotations

import json
from typing import Any

import pytest

from toolwright.core.compile.grouper import filter_by_scope, load_groups_index, suggest_group_name
from toolwright.models.groups import ToolGroup, ToolGroupIndex


def _make_groups_index() -> ToolGroupIndex:
    """Create a test ToolGroupIndex with known groups."""
    return ToolGroupIndex(
        groups=[
            ToolGroup(name="products", tools=["get_products", "create_product"], path_prefix="/products", description="Products endpoints (2 tools)"),
            ToolGroup(name="orders", tools=["get_orders", "create_order", "delete_order"], path_prefix="/orders", description="Orders endpoints (3 tools)"),
            ToolGroup(name="repos", tools=["get_repo", "create_repo"], path_prefix="/repos", description="Repos endpoints (2 tools)"),
            ToolGroup(name="repos/issues", tools=["get_issues", "create_issue"], path_prefix="/repos/*/issues", description="Repos > Issues endpoints (2 tools)"),
            ToolGroup(name="repos/pulls", tools=["get_pulls"], path_prefix="/repos/*/pulls", description="Repos > Pulls endpoints (1 tools)"),
        ],
        ungrouped=[],
        generated_from="auto",
    )


def _make_actions(names: list[str]) -> dict[str, dict[str, Any]]:
    """Create minimal action dicts keyed by name."""
    return {n: {"name": n, "path": "/test", "method": "GET", "host": "example.com"} for n in names}


def test_scope_filters_to_named_group():
    """--scope products returns only product tools."""
    index = _make_groups_index()
    all_names = ["get_products", "create_product", "get_orders", "create_order", "delete_order"]
    actions = _make_actions(all_names)
    filtered = filter_by_scope(actions, "products", index)
    assert sorted(filtered.keys()) == ["create_product", "get_products"]


def test_scope_multiple_groups():
    """--scope products,orders returns union of both."""
    index = _make_groups_index()
    all_names = ["get_products", "create_product", "get_orders", "create_order", "delete_order"]
    actions = _make_actions(all_names)
    filtered = filter_by_scope(actions, "products,orders", index)
    assert sorted(filtered.keys()) == ["create_order", "create_product", "delete_order", "get_orders", "get_products"]


def test_scope_prefix_matching():
    """--scope repos matches repos, repos/issues, repos/pulls."""
    index = _make_groups_index()
    all_names = ["get_repo", "create_repo", "get_issues", "create_issue", "get_pulls", "get_products"]
    actions = _make_actions(all_names)
    filtered = filter_by_scope(actions, "repos", index)
    assert sorted(filtered.keys()) == ["create_issue", "create_repo", "get_issues", "get_pulls", "get_repo"]


def test_scope_unknown_group_raises():
    """Unknown group name raises ValueError."""
    index = _make_groups_index()
    actions = _make_actions(["get_products"])
    with pytest.raises(ValueError, match="Unknown group"):
        filter_by_scope(actions, "prodcts", index)


def test_suggest_group_name_close_match():
    """Close misspelling produces suggestion."""
    available = ["products", "orders", "repos"]
    assert suggest_group_name("prodcts", available) == "products"


def test_suggest_group_name_no_match():
    """Unrelated name returns None."""
    available = ["products", "orders", "repos"]
    assert suggest_group_name("zzzzz", available) is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_serve_scope.py -v -x`
Expected: FAIL — `ImportError`

**Step 3: Add `filter_by_scope`, `load_groups_index`, `suggest_group_name` to `grouper.py`**

Append to `toolwright/core/compile/grouper.py`:

```python
def suggest_group_name(name: str, available: list[str]) -> str | None:
    """Suggest a group name using simple edit distance."""
    best: str | None = None
    best_dist = 3  # max distance threshold
    for candidate in available:
        dist = _levenshtein(name.lower(), candidate.lower())
        if dist < best_dist:
            best_dist = dist
            best = candidate
        # Also check prefix match
        if candidate.startswith(name.lower()) or name.lower().startswith(candidate):
            return candidate
    return best


def _levenshtein(s: str, t: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s) < len(t):
        return _levenshtein(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        curr = [i + 1]
        for j, tc in enumerate(t):
            cost = 0 if sc == tc else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def load_groups_index(groups_path: str | None) -> ToolGroupIndex | None:
    """Load a ToolGroupIndex from a groups.json file path.

    Returns None if path is None or file doesn't exist.
    """
    import json as json_mod
    from pathlib import Path

    if groups_path is None:
        return None
    path = Path(groups_path)
    if not path.exists():
        return None
    with open(path) as f:
        data = json_mod.load(f)
    return ToolGroupIndex.from_dict(data)


def filter_by_scope(
    actions: dict[str, dict[str, Any]],
    scope: str,
    groups_index: ToolGroupIndex,
) -> dict[str, dict[str, Any]]:
    """Filter actions to only those in the named groups.

    Scope is a comma-separated list of group names.
    Prefix matching: 'repos' matches 'repos', 'repos/issues', 'repos/pulls'.
    """
    requested = [s.strip().lower() for s in scope.split(",") if s.strip()]
    available_names = [g.name for g in groups_index.groups]

    # Validate group names
    for name in requested:
        # Check for exact or prefix match
        matches = [g for g in available_names if g == name or g.startswith(name + "/")]
        if not matches:
            suggestion = suggest_group_name(name, available_names)
            msg = f"Unknown group '{name}'."
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            msg += f" Available groups: {', '.join(sorted(available_names))}"
            raise ValueError(msg)

    # Collect tool IDs from matching groups
    allowed_tools: set[str] = set()
    for group in groups_index.groups:
        for name in requested:
            if group.name == name or group.name.startswith(name + "/"):
                allowed_tools.update(group.tools)
                break

    return {k: v for k, v in actions.items() if k in allowed_tools}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_serve_scope.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add toolwright/core/compile/grouper.py tests/test_serve_scope.py
git commit -m "feat: add scope filtering with prefix matching and fuzzy suggestions"
```

---

### Task 8: Serve Command — `--scope` and `--no-tool-limit` Options

**Files:**
- Modify: `toolwright/cli/commands_mcp.py`
- Modify: `toolwright/cli/mcp.py`
- Modify: `tests/test_serve_scope.py`

**Step 1: Write failing tests for guardrails**

Append to `tests/test_serve_scope.py`:

```python
from toolwright.cli.mcp import check_tool_count_guardrails


def test_no_warn_at_30():
    """Exactly 30 tools: no warning."""
    warnings, block = check_tool_count_guardrails(30, groups_index=None, no_tool_limit=False)
    assert warnings == []
    assert block is False


def test_warn_above_30():
    """50 tools: warning, no block."""
    warnings, block = check_tool_count_guardrails(50, groups_index=None, no_tool_limit=False)
    assert len(warnings) > 0
    assert block is False


def test_block_above_200():
    """201 tools: block."""
    warnings, block = check_tool_count_guardrails(201, groups_index=None, no_tool_limit=False)
    assert block is True


def test_block_override():
    """201 tools + no_tool_limit: warning, no block."""
    warnings, block = check_tool_count_guardrails(201, groups_index=None, no_tool_limit=True)
    assert block is False
    assert len(warnings) > 0


def test_warn_with_groups_suggests_scope():
    """Warning includes group suggestions when groups_index available."""
    index = _make_groups_index()
    warnings, block = check_tool_count_guardrails(50, groups_index=index, no_tool_limit=False)
    combined = "\n".join(warnings)
    assert "--scope" in combined
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_serve_scope.py::test_no_warn_at_30 -v -x`
Expected: FAIL — `ImportError: cannot import name 'check_tool_count_guardrails'`

**Step 3: Add guardrails function to `toolwright/cli/mcp.py`**

Add at the top of `mcp.py`:

```python
TOOL_COUNT_WARN_THRESHOLD = 30
TOOL_COUNT_BLOCK_THRESHOLD = 200
```

Add the function:

```python
def check_tool_count_guardrails(
    tool_count: int,
    *,
    groups_index: Any | None,
    no_tool_limit: bool,
) -> tuple[list[str], bool]:
    """Check tool count against thresholds, return (warnings, should_block).

    Returns:
        Tuple of (warning messages, True if server should not start).
    """
    warnings: list[str] = []
    block = False

    if tool_count <= TOOL_COUNT_WARN_THRESHOLD:
        return warnings, block

    # Build group suggestion text
    group_hint = ""
    if groups_index is not None:
        from toolwright.models.groups import ToolGroupIndex

        if isinstance(groups_index, ToolGroupIndex) and groups_index.groups:
            top_groups = sorted(groups_index.groups, key=lambda g: len(g.tools), reverse=True)[:8]
            parts = [f"{g.name} ({len(g.tools)})" for g in top_groups]
            group_hint = (
                "\n  Consider narrowing with --scope:\n    "
                + "    ".join(f"{p:<20}" for p in parts)
                + f"\n  Example: toolwright serve --scope {top_groups[0].name}"
            )
        else:
            group_hint = "\n  Run 'toolwright compile' to generate tool groups, then use --scope to narrow."
    else:
        group_hint = "\n  Run 'toolwright compile' to generate tool groups, then use --scope to narrow."

    if tool_count > TOOL_COUNT_BLOCK_THRESHOLD:
        if no_tool_limit:
            warnings.append(
                f"Serving {tool_count} tools (--no-tool-limit override active). "
                f"Agent performance degrades above ~{TOOL_COUNT_WARN_THRESHOLD} tools."
                + group_hint
            )
        else:
            warnings.append(
                f"Refusing to serve {tool_count} tools. "
                f"Agents cannot reliably select from this many tools."
                + group_hint
            )
            block = True
    else:
        warnings.append(
            f"Serving {tool_count} tools. "
            f"Agent performance degrades above ~{TOOL_COUNT_WARN_THRESHOLD} tools."
            + group_hint
        )

    return warnings, block
```

**Step 4: Run guardrail tests**

Run: `python -m pytest tests/test_serve_scope.py -v`
Expected: PASS (all tests)

**Step 5: Wire `--scope` and `--no-tool-limit` into CLI**

In `toolwright/cli/commands_mcp.py`, add two new options to the `serve` command (after `--max-risk`):

```python
@click.option(
    "--scope", "-s",
    type=str,
    default=None,
    help="Comma-separated tool groups to serve (e.g., 'products,orders'). Use 'toolwright groups list' to see available groups.",
)
@click.option(
    "--no-tool-limit",
    is_flag=True,
    default=False,
    help="Override the 200-tool safety limit. Not recommended.",
)
```

Add `scope: str | None` and `no_tool_limit: bool` to the `serve` function signature.

Pass them through to `run_mcp_serve()`:

```python
scope=scope,
no_tool_limit=no_tool_limit,
```

In `toolwright/cli/mcp.py`, add `scope: str | None = None` and `no_tool_limit: bool = False` to `run_mcp_serve()` signature.

After the existing `filter_actions` call (around line 897), add scope filtering and guardrails:

```python
    # Scope filtering (requires groups.json from toolpack)
    groups_index = None
    if scope or not no_tool_limit:
        groups_json_path = None
        if resolved_toolpack_paths is not None:
            groups_json_path = resolved_toolpack_paths.groups_path
        elif resolved_tools_path is not None:
            candidate = resolved_tools_path.parent / "groups.json"
            if candidate.exists():
                groups_json_path = candidate

        from toolwright.core.compile.grouper import load_groups_index
        groups_index = load_groups_index(str(groups_json_path) if groups_json_path else None)

    if scope:
        if groups_index is None:
            click.echo(
                "Warning: No tool groups found. Run 'toolwright compile' to generate groups.\n"
                f"Serving all {len(server.actions)} tools.",
                err=True,
            )
        else:
            from toolwright.core.compile.grouper import filter_by_scope
            try:
                server.actions = filter_by_scope(server.actions, scope, groups_index)
                server.pipeline.actions = server.actions
            except ValueError as exc:
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)

    # Tool count guardrails
    tool_count = len(server.actions)
    warnings, should_block = check_tool_count_guardrails(
        tool_count, groups_index=groups_index, no_tool_limit=no_tool_limit,
    )
    for warning in warnings:
        click.echo(f"  {warning}", err=True)
    if should_block:
        sys.exit(1)
```

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 7: Commit**

```bash
git add toolwright/cli/commands_mcp.py toolwright/cli/mcp.py tests/test_serve_scope.py
git commit -m "feat: add --scope and --no-tool-limit to serve command with guardrails"
```

---

### Task 9: Groups CLI — `groups list` and `groups show`

**Files:**
- Create: `toolwright/cli/commands_groups.py`
- Modify: `toolwright/cli/main.py`
- Create: `tests/test_groups_cli.py`

**Step 1: Write failing tests**

Create `tests/test_groups_cli.py`:

```python
"""Tests for groups CLI commands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


def _write_toolpack_with_groups(tmp_path: Path) -> Path:
    """Write a minimal toolpack with groups.json."""
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    artifact_dir.mkdir(parents=True)

    tools = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {"name": "get_products", "method": "GET", "path": "/products", "host": "api.example.com", "signature_id": "sig_gp", "tool_id": "sig_gp", "input_schema": {"type": "object", "properties": {}}},
            {"name": "create_product", "method": "POST", "path": "/products", "host": "api.example.com", "signature_id": "sig_cp", "tool_id": "sig_cp", "input_schema": {"type": "object", "properties": {}}},
            {"name": "get_orders", "method": "GET", "path": "/orders", "host": "api.example.com", "signature_id": "sig_go", "tool_id": "sig_go", "input_schema": {"type": "object", "properties": {}}},
        ],
    }
    (artifact_dir / "tools.json").write_text(json.dumps(tools))

    groups = {
        "groups": [
            {"name": "orders", "tools": ["get_orders"], "path_prefix": "/orders", "description": "Orders endpoints (1 tools)"},
            {"name": "products", "tools": ["get_products", "create_product"], "path_prefix": "/products", "description": "Products endpoints (2 tools)"},
        ],
        "ungrouped": [],
        "generated_from": "auto",
    }
    (artifact_dir / "groups.json").write_text(json.dumps(groups))

    (artifact_dir / "toolsets.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "toolsets": {}}))
    (artifact_dir / "policy.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "name": "Test", "default_action": "allow", "rules": []}))
    (artifact_dir / "baseline.json").write_text(json.dumps({"version": "1.0.0", "schema_version": "1.0"}))

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(yaml.safe_dump({
        "version": "1.0.0",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        "created_at": "2026-01-01T00:00:00",
        "capture_id": "cap_test",
        "artifact_id": "art_test",
        "scope": "default",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com", "name": "Test"},
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "groups": "artifact/groups.json",
        },
    }))
    return toolpack_path


def test_groups_list_output(tmp_path: Path):
    """groups list shows group names and counts."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "list", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "products" in result.output
    assert "orders" in result.output
    assert "2 tools" in result.output or "2" in result.output


def test_groups_show_existing(tmp_path: Path):
    """groups show <name> lists tools in the group."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "show", "products", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "get_products" in result.output
    assert "create_product" in result.output


def test_groups_show_nonexistent(tmp_path: Path):
    """groups show with wrong name gives error with suggestion."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "show", "prodcts", "--toolpack", str(toolpack_path)])
    assert result.exit_code != 0
    assert "prodcts" in result.output


def test_groups_list_no_groups_file(tmp_path: Path):
    """groups list gracefully handles missing groups.json."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    # Remove groups.json
    groups_file = toolpack_path.parent / "artifact" / "groups.json"
    groups_file.unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "list", "--toolpack", str(toolpack_path)])
    assert "No tool groups found" in result.output or result.exit_code != 0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_groups_cli.py -v -x`
Expected: FAIL — `Error: No such command 'groups'`

**Step 3: Create `toolwright/cli/commands_groups.py`**

```python
"""Groups command group for listing and inspecting tool groups."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click


def register_groups_commands(*, cli: click.Group) -> None:
    """Register the groups command group on the provided CLI group."""

    @cli.group()
    def groups() -> None:
        """List and inspect auto-generated tool groups."""

    @groups.command("list")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml",
    )
    @click.pass_context
    def groups_list(ctx: click.Context, toolpack: str | None) -> None:
        """List all tool groups with their tool counts.

        \b
        Examples:
          toolwright groups list
          toolwright groups list --toolpack toolpack.yaml
        """
        groups_path = _resolve_groups_path(toolpack, ctx)
        if groups_path is None or not groups_path.exists():
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        from toolwright.core.compile.grouper import load_groups_index

        index = load_groups_index(str(groups_path))
        if index is None or not index.groups:
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        total_tools = sum(len(g.tools) for g in index.groups) + len(index.ungrouped)
        click.echo(f"\nGroups ({len(index.groups)} groups, {total_tools} tools total):\n")

        # Find max name length for alignment
        max_name = max(len(g.name) for g in index.groups)
        for group in index.groups:
            count_str = f"{len(group.tools)} tools"
            desc = group.description or ""
            click.echo(f"  {group.name:<{max_name + 2}} {count_str:>10}   {desc}")

        if index.ungrouped:
            click.echo(f"\n  Ungrouped: {len(index.ungrouped)} tools")

        click.echo(f"\nServe a subset: toolwright serve --scope <group1>,<group2>")

    @groups.command("show")
    @click.argument("name")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml",
    )
    @click.pass_context
    def groups_show(ctx: click.Context, name: str, toolpack: str | None) -> None:
        """Show tools in a specific group.

        \b
        Examples:
          toolwright groups show products
          toolwright groups show repos/issues --toolpack toolpack.yaml
        """
        groups_path = _resolve_groups_path(toolpack, ctx)
        if groups_path is None or not groups_path.exists():
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        from toolwright.core.compile.grouper import load_groups_index, suggest_group_name

        index = load_groups_index(str(groups_path))
        if index is None:
            click.echo("No tool groups found.", err=True)
            ctx.exit(1)
            return

        # Find the group
        group = next((g for g in index.groups if g.name == name.lower()), None)
        if group is None:
            available = [g.name for g in index.groups]
            suggestion = suggest_group_name(name, available)
            msg = f"Error: Unknown group '{name}'."
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            msg += f"\nAvailable: {', '.join(sorted(available))}"
            click.echo(msg, err=True)
            ctx.exit(1)
            return

        # Load tools.json for method/path details
        tools_path = _resolve_tools_path(toolpack, ctx)
        action_details: dict[str, dict[str, str]] = {}
        if tools_path and tools_path.exists():
            with open(tools_path) as f:
                manifest = json.load(f)
            for action in manifest.get("actions", []):
                action_details[action["name"]] = {
                    "method": action.get("method", "GET"),
                    "path": action.get("path", "/"),
                }

        click.echo(f"\nGroup: {group.name} ({len(group.tools)} tools)")
        click.echo(f"Path prefix: {group.path_prefix}\n")

        for tool_name in group.tools:
            detail = action_details.get(tool_name, {})
            method = detail.get("method", "")
            path = detail.get("path", "")
            click.echo(f"  {tool_name:<30} {method:<7} {path}")

        click.echo(f"\nServe this group: toolwright serve --scope {group.name}")


def _resolve_groups_path(toolpack: str | None, ctx: click.Context) -> Path | None:
    """Resolve groups.json path from toolpack or auto-discovery."""
    if toolpack:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(toolpack)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=toolpack)
        return resolved.groups_path

    # Auto-resolve toolpack
    try:
        from toolwright.utils.resolve import resolve_toolpack_path

        tp_path = resolve_toolpack_path(root=ctx.obj.get("root") if ctx.obj else None)
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=tp_path)
        return resolved.groups_path
    except (FileNotFoundError, click.UsageError):
        return None


def _resolve_tools_path(toolpack: str | None, ctx: click.Context) -> Path | None:
    """Resolve tools.json path from toolpack or auto-discovery."""
    if toolpack:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(toolpack)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=toolpack)
        return resolved.tools_path

    try:
        from toolwright.utils.resolve import resolve_toolpack_path

        tp_path = resolve_toolpack_path(root=ctx.obj.get("root") if ctx.obj else None)
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=tp_path)
        return resolved.tools_path
    except (FileNotFoundError, click.UsageError):
        return None
```

**Step 4: Register in `main.py`**

In `toolwright/cli/main.py`, add import:

```python
from toolwright.cli.commands_groups import register_groups_commands
```

After the existing `register_snapshot_commands(cli=cli)` line (~line 1372), add:

```python
register_groups_commands(cli=cli)
```

**Step 5: Run tests**

Run: `python -m pytest tests/test_groups_cli.py -v`
Expected: PASS (all tests)

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 7: Commit**

```bash
git add toolwright/cli/commands_groups.py toolwright/cli/main.py tests/test_groups_cli.py
git commit -m "feat: add 'groups list' and 'groups show' CLI commands"
```

---

### Task 10: Startup Card — Show Scope Info

**Files:**
- Modify: `toolwright/mcp/startup_card.py`

**Step 1: Write failing test**

Append to `tests/test_serve_scope.py`:

```python
from toolwright.mcp.startup_card import render_startup_card


def test_startup_card_shows_scope():
    """Startup card includes scope info when provided."""
    card = render_startup_card(
        name="Test API",
        tools={"read": 10, "write": 5},
        risk_counts={"low": 10, "medium": 5},
        context_tokens=5000,
        tokens_per_tool=333,
        scope_info="products, orders",
        total_compiled=1183,
    )
    assert "products, orders" in card
    assert "1183" in card


def test_startup_card_no_scope():
    """Startup card works without scope info."""
    card = render_startup_card(
        name="Test API",
        tools={"read": 10},
        risk_counts={"low": 10},
        context_tokens=3000,
        tokens_per_tool=300,
    )
    assert "Test API" in card
```

**Step 2: Run to verify failure**

Run: `python -m pytest tests/test_serve_scope.py::test_startup_card_shows_scope -v -x`
Expected: FAIL — `TypeError: render_startup_card() got an unexpected keyword argument 'scope_info'`

**Step 3: Modify `toolwright/mcp/startup_card.py`**

Add `scope_info: str | None = None` and `total_compiled: int | None = None` to `render_startup_card()` params.

After the `total_tools` line, add:

```python
    if scope_info and total_compiled:
        tool_line = f"  Tools:    {total_tools} (scope: {scope_info}) of {total_compiled} compiled"
    elif scope_info:
        tool_line = f"  Tools:    {total_tools} (scope: {scope_info})"
    else:
        tool_line = f"  Tools:    {total_tools} ({tool_parts})"
```

Replace the existing tools line in `lines` with `tool_line`.

**Step 4: Run tests**

Run: `python -m pytest tests/test_serve_scope.py::test_startup_card_shows_scope tests/test_serve_scope.py::test_startup_card_no_scope -v`
Expected: PASS

**Step 5: Commit**

```bash
git add toolwright/mcp/startup_card.py tests/test_serve_scope.py
git commit -m "feat: show scope info in MCP startup card"
```

---

### Task 11: Gate Integration — `--scope` on allow/block, `--by-group` on status

**Files:**
- Modify: `toolwright/cli/commands_approval.py`
- Create: `tests/test_gate_scope.py`

**Step 1: Write failing test**

Create `tests/test_gate_scope.py`:

```python
"""Tests for gate --scope integration."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


def _write_full_toolpack(tmp_path: Path) -> Path:
    """Write a toolpack with tools, groups, and pending lockfile."""
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    artifact_dir.mkdir(parents=True)
    lockfile_dir.mkdir(parents=True)

    tools = {
        "version": "1.0.0", "schema_version": "1.0", "name": "Test",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {"name": "get_products", "method": "GET", "path": "/products", "host": "api.example.com", "signature_id": "sig_gp", "tool_id": "sig_gp", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "low"},
            {"name": "create_product", "method": "POST", "path": "/products", "host": "api.example.com", "signature_id": "sig_cp", "tool_id": "sig_cp", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "medium"},
            {"name": "get_orders", "method": "GET", "path": "/orders", "host": "api.example.com", "signature_id": "sig_go", "tool_id": "sig_go", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "low"},
        ],
    }
    (artifact_dir / "tools.json").write_text(json.dumps(tools))
    (artifact_dir / "toolsets.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "toolsets": {"readonly": {"actions": ["get_products", "get_orders"]}}}))
    (artifact_dir / "policy.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "name": "Test", "default_action": "allow", "rules": []}))
    (artifact_dir / "baseline.json").write_text(json.dumps({"version": "1.0.0", "schema_version": "1.0"}))
    (artifact_dir / "groups.json").write_text(json.dumps({
        "groups": [
            {"name": "orders", "tools": ["get_orders"], "path_prefix": "/orders", "description": "Orders (1 tools)"},
            {"name": "products", "tools": ["get_products", "create_product"], "path_prefix": "/products", "description": "Products (2 tools)"},
        ],
        "ungrouped": [],
        "generated_from": "auto",
    }))

    # Create a pending lockfile (gate sync would normally create this)
    (lockfile_dir / "toolwright.lock.pending.yaml").write_text(yaml.safe_dump({
        "version": "1.0.0", "schema_version": "1.0", "tools": {},
    }))

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(yaml.safe_dump({
        "version": "1.0.0", "schema_version": "1.0",
        "toolpack_id": "tp_test", "created_at": "2026-01-01T00:00:00",
        "capture_id": "cap_test", "artifact_id": "art_test", "scope": "default",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com"},
        "paths": {
            "tools": "artifact/tools.json", "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml", "baseline": "artifact/baseline.json",
            "groups": "artifact/groups.json",
            "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
        },
    }))
    return toolpack_path


def test_gate_status_by_group(tmp_path: Path):
    """gate status --by-group shows per-group summary."""
    toolpack_path = _write_full_toolpack(tmp_path)
    # First sync to create tool entries in lockfile
    runner = CliRunner()
    runner.invoke(cli, ["gate", "sync", "--toolpack", str(toolpack_path)])

    result = runner.invoke(cli, ["gate", "status", "--by-group", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "products" in result.output
    assert "orders" in result.output
```

**Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gate_scope.py::test_gate_status_by_group -v -x`
Expected: FAIL — `Error: No such option '--by-group'`

**Step 3: Add `--by-group` to `gate status`**

In `toolwright/cli/commands_approval.py`, add `--by-group` option to `gate_status`:

```python
@click.option(
    "--by-group",
    is_flag=True,
    help="Show approval summary grouped by tool group",
)
```

Add `by_group: bool` to the `gate_status` function signature.

When `by_group` is True, load groups.json and display a per-group summary:

```python
if by_group:
    # Load groups index
    groups_path = None
    if toolpack:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths as rtp
        tp = load_toolpack(toolpack)
        resolved_tp = rtp(toolpack=tp, toolpack_path=toolpack)
        groups_path = resolved_tp.groups_path

    if groups_path and groups_path.exists():
        from toolwright.core.compile.grouper import load_groups_index
        groups_index = load_groups_index(str(groups_path))
        if groups_index:
            from toolwright.cli.approve import run_approve_list_by_group
            run_approve_list_by_group(
                lockfile_path=lockfile,
                groups_index=groups_index,
                verbose=ctx.obj.get("verbose", False),
            )
            return
    click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
    ctx.exit(1)
    return
```

Add `run_approve_list_by_group` function to `toolwright/cli/approve.py`:

```python
def run_approve_list_by_group(
    lockfile_path: str | None,
    groups_index: Any,
    verbose: bool = False,
) -> None:
    """Display approval status grouped by tool group."""
    from toolwright.core.approval import LockfileManager
    from toolwright.models.groups import ToolGroupIndex

    lockfile = lockfile_path or "toolwright.lock.yaml"
    manager = LockfileManager(lockfile)
    if not manager.exists():
        click.echo(f"No lockfile found at {lockfile}")
        return

    lf = manager.load()
    tool_statuses = {t.tool_id: t.status.value for t in lf.tools.values()}

    for group in groups_index.groups:
        approved = sum(1 for t in group.tools if tool_statuses.get(t) == "approved")
        pending = sum(1 for t in group.tools if tool_statuses.get(t, "pending") == "pending")
        rejected = sum(1 for t in group.tools if tool_statuses.get(t) == "rejected")

        parts = []
        if approved:
            parts.append(f"{approved} approved")
        if pending:
            parts.append(f"{pending} pending")
        if rejected:
            parts.append(f"{rejected} rejected")

        status_str = ", ".join(parts) if parts else "unknown"
        click.echo(f"  {group.name} ({len(group.tools)} tools)    {status_str}")
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_gate_scope.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add toolwright/cli/commands_approval.py toolwright/cli/approve.py tests/test_gate_scope.py
git commit -m "feat: add --by-group to gate status for per-group approval summary"
```

---

### Task 12: Compile Output — Group Summary

**Files:**
- Modify: `toolwright/cli/compile.py`
- Modify: `toolwright/cli/mint.py`

**Step 1: Add group summary printing after compile**

In `toolwright/cli/compile.py`, in `run_compile()`, after the existing output lines (around line 637), add:

```python
    if result.groups_path and result.groups_path.exists():
        from toolwright.core.compile.grouper import load_groups_index
        groups_index = load_groups_index(str(result.groups_path))
        if groups_index and groups_index.groups:
            _print_group_summary(groups_index, result.endpoint_count)
```

Add helper function:

```python
def _print_group_summary(groups_index: Any, total_tools: int) -> None:
    """Print a compact group summary after compile."""
    from toolwright.models.groups import ToolGroupIndex

    click.echo(f"\n  {total_tools} tools in {len(groups_index.groups)} groups")

    # Show top 8 groups by tool count
    top = sorted(groups_index.groups, key=lambda g: len(g.tools), reverse=True)[:8]
    parts = [f"{g.name} ({len(g.tools)})" for g in top]

    # Format in rows of 4
    for i in range(0, len(parts), 4):
        row = "    ".join(f"{p:<20}" for p in parts[i : i + 4])
        click.echo(f"    {row}")

    if len(groups_index.groups) > 8:
        click.echo(f"    ... ({len(groups_index.groups) - 8} more)")

    click.echo(f"\n  Serve subset: toolwright serve --scope {top[0].name}")
    click.echo(f"  All groups:  toolwright groups list")
```

**Step 2: Add same output to `run_mint()` in `mint.py`**

After the existing "Mint complete" output (around line 368), before the auth detection output, add similar group summary:

```python
    # Show group summary if groups were generated
    copied_groups = artifact_dir / "groups.json"
    if copied_groups.exists():
        from toolwright.core.compile.grouper import load_groups_index
        groups_idx = load_groups_index(str(copied_groups))
        if groups_idx and groups_idx.groups:
            total = sum(len(g.tools) for g in groups_idx.groups) + len(groups_idx.ungrouped)
            click.echo(f"\n  {total} tools in {len(groups_idx.groups)} groups")
            top = sorted(groups_idx.groups, key=lambda g: len(g.tools), reverse=True)[:8]
            parts_list = [f"{g.name} ({len(g.tools)})" for g in top]
            for j in range(0, len(parts_list), 4):
                row = "    ".join(f"{p:<20}" for p in parts_list[j : j + 4])
                click.echo(f"    {row}")
            if len(groups_idx.groups) > 8:
                click.echo(f"    ... ({len(groups_idx.groups) - 8} more)")
            click.echo(f"\n  Serve subset: toolwright serve --scope {top[0].name}")
            click.echo(f"  All groups:  toolwright groups list")
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v -x --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 4: Commit**

```bash
git add toolwright/cli/compile.py toolwright/cli/mint.py
git commit -m "feat: print group summary after compile and mint"
```

---

### Task 13: Documentation and Cleanup

**Files:**
- Modify: `CAPABILITIES.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/known-limitations.md`

**Step 1: Update CAPABILITIES.md**

Add new capability entries for:
- `CAP-GROUP-001`: Auto-generated tool groups
- `CAP-SERVE-002`: Serve-time scope filtering
- `CAP-SERVE-003`: Tool count guardrails

**Step 2: Update user-guide.md**

Add section on tool groups:
- How groups are generated during compile
- Using `--scope` to serve a subset
- Using `groups list` and `groups show`
- Using `--by-group` with gate status

**Step 3: Update known-limitations.md**

Note that manual group editing is deferred (groups.json can be edited by hand).

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=30 -q 2>&1 | tail -10`
Expected: All pass

**Step 5: Run lint**

Run: `ruff check toolwright/ tests/`
Expected: No errors

**Step 6: Commit**

```bash
git add CAPABILITIES.md docs/user-guide.md docs/known-limitations.md
git commit -m "docs: add tool groups documentation to capability registry and user guide"
```

---

### Task 14: Final Integration Verification

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All pass

**Step 2: Run linter**

Run: `ruff check toolwright/ tests/`
Expected: Clean

**Step 3: Verify manually with a synthetic large toolpack**

Create a test script that generates 300+ actions and confirms:
- groups.json is generated with auto-split
- `toolwright serve --scope <group>` filters correctly
- `toolwright serve` without scope blocks at 200+ tools
- `toolwright groups list` shows all groups
- `toolwright groups show <name>` shows tools

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete tool groups, serve-time scoping, and tool count guardrails"
```
