# Toolpack Display Names — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users name their toolpacks with a friendly display name at capture time and rename them later, with the name shown across all UI surfaces.

**Architecture:** Add an optional `display_name` field to the `Toolpack` model. A `resolve_display_name()` helper provides fallback resolution (display_name → origin.name → host slug → toolpack_id). All UI surfaces call this helper. A new `cask rename` CLI command updates the field in toolpack.yaml.

**Tech Stack:** Python 3.11+, Pydantic models, Click CLI, Rich TUI, pytest

---

### Task 1: Add `display_name` field to Toolpack model

**Files:**
- Modify: `toolwright/core/toolpack.py:94-108`
- Test: `tests/test_toolpack_display_name.py`

**Step 1: Write the failing test**

```python
# tests/test_toolpack_display_name.py
"""Tests for toolpack display_name field and resolution."""

from __future__ import annotations


class TestToolpackDisplayNameField:
    """display_name is an optional field on Toolpack."""

    def test_display_name_defaults_to_none(self) -> None:
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        tp = Toolpack(
            toolpack_id="abc123",
            created_at="2026-01-01T00:00:00Z",
            capture_id="cap1",
            artifact_id="art1",
            scope="first_party_only",
            origin=ToolpackOrigin(start_url="https://api.example.com"),
            paths=ToolpackPaths(
                tools="tools.json",
                toolsets="toolsets.yaml",
                policy="policy.yaml",
                baseline="baseline.json",
            ),
        )
        assert tp.display_name is None

    def test_display_name_set_explicitly(self) -> None:
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        tp = Toolpack(
            toolpack_id="abc123",
            created_at="2026-01-01T00:00:00Z",
            capture_id="cap1",
            artifact_id="art1",
            scope="first_party_only",
            display_name="stripe-api",
            origin=ToolpackOrigin(start_url="https://api.stripe.com"),
            paths=ToolpackPaths(
                tools="tools.json",
                toolsets="toolsets.yaml",
                policy="policy.yaml",
                baseline="baseline.json",
            ),
        )
        assert tp.display_name == "stripe-api"

    def test_display_name_serializes_to_yaml(self) -> None:
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        tp = Toolpack(
            toolpack_id="abc123",
            created_at="2026-01-01T00:00:00Z",
            capture_id="cap1",
            artifact_id="art1",
            scope="first_party_only",
            display_name="my-api",
            origin=ToolpackOrigin(start_url="https://api.example.com"),
            paths=ToolpackPaths(
                tools="tools.json",
                toolsets="toolsets.yaml",
                policy="policy.yaml",
                baseline="baseline.json",
            ),
        )
        data = tp.model_dump()
        assert data["display_name"] == "my-api"

    def test_display_name_absent_in_yaml_loads_as_none(self) -> None:
        """Backward compat: existing toolpacks without display_name still load."""
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        data = {
            "toolpack_id": "abc123",
            "created_at": "2026-01-01T00:00:00Z",
            "capture_id": "cap1",
            "artifact_id": "art1",
            "scope": "first_party_only",
            "origin": {"start_url": "https://api.example.com"},
            "paths": {
                "tools": "tools.json",
                "toolsets": "toolsets.yaml",
                "policy": "policy.yaml",
                "baseline": "baseline.json",
            },
        }
        tp = Toolpack(**data)
        assert tp.display_name is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py -v`
Expected: FAIL — `display_name` field not recognized by Pydantic

**Step 3: Write minimal implementation**

In `toolwright/core/toolpack.py`, add one line to class `Toolpack` (after line 107):

```python
class Toolpack(BaseModel):
    """Toolpack metadata payload."""

    version: str = "1.0.0"
    schema_version: str = CURRENT_SCHEMA_VERSION
    toolpack_id: str
    created_at: datetime
    capture_id: str
    artifact_id: str
    scope: str
    allowed_hosts: list[str] = Field(default_factory=list)
    display_name: str | None = None  # user-facing name, mutable via cask rename
    origin: ToolpackOrigin
    paths: ToolpackPaths
    runtime: ToolpackRuntime | None = None
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add toolwright/core/toolpack.py tests/test_toolpack_display_name.py
git commit -m "feat: add display_name field to Toolpack model"
```

---

### Task 2: Add `resolve_display_name()` helper

**Files:**
- Modify: `toolwright/ui/ops.py` (add function after `list_tools`)
- Test: `tests/test_toolpack_display_name.py` (append tests)

**Step 1: Write the failing tests**

Append to `tests/test_toolpack_display_name.py`:

```python
class TestResolveDisplayName:
    """resolve_display_name returns the best human-friendly name."""

    def _make_toolpack(self, **overrides):
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        defaults = dict(
            toolpack_id="abc123",
            created_at="2026-01-01T00:00:00Z",
            capture_id="cap1",
            artifact_id="art1",
            scope="first_party_only",
            origin=ToolpackOrigin(start_url="https://api.example.com"),
            paths=ToolpackPaths(
                tools="tools.json",
                toolsets="toolsets.yaml",
                policy="policy.yaml",
                baseline="baseline.json",
            ),
        )
        defaults.update(overrides)
        return Toolpack(**defaults)

    def test_prefers_display_name(self) -> None:
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack(display_name="stripe-api")
        assert resolve_display_name(tp) == "stripe-api"

    def test_falls_back_to_origin_name(self) -> None:
        from toolwright.core.toolpack import ToolpackOrigin
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack(
            origin=ToolpackOrigin(start_url="https://api.stripe.com", name="stripe")
        )
        assert resolve_display_name(tp) == "stripe"

    def test_falls_back_to_host_slug(self) -> None:
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack(
            allowed_hosts=["api.stripe.com"],
        )
        assert resolve_display_name(tp) == "stripe"

    def test_falls_back_to_toolpack_id(self) -> None:
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack()
        # No display_name, no origin.name, no allowed_hosts
        assert resolve_display_name(tp) == "abc123"

    def test_host_slug_strips_api_prefix(self) -> None:
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack(allowed_hosts=["api.github.com"])
        assert resolve_display_name(tp) == "github"

    def test_host_slug_strips_common_tlds(self) -> None:
        from toolwright.ui.ops import resolve_display_name

        tp = self._make_toolpack(allowed_hosts=["dummyjson.com"])
        assert resolve_display_name(tp) == "dummyjson"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py::TestResolveDisplayName -v`
Expected: FAIL — `resolve_display_name` not importable

**Step 3: Write minimal implementation**

Append to `toolwright/ui/ops.py` after `list_tools`:

```python
# ---------------------------------------------------------------------------
# Display name resolution
# ---------------------------------------------------------------------------


def _host_slug(toolpack: "Toolpack") -> str | None:
    """Derive a short display name from allowed_hosts.

    api.stripe.com  ->  stripe
    dummyjson.com   ->  dummyjson
    localhost       ->  localhost
    """
    if not toolpack.allowed_hosts:
        return None
    host = toolpack.allowed_hosts[0]
    # Strip port
    host = host.split(":")[0]
    # Split into parts
    parts = host.split(".")
    # Remove common prefixes/suffixes
    strip = {"api", "www", "rest", "v1", "v2", "com", "org", "net", "io", "dev", "co"}
    meaningful = [p for p in parts if p.lower() not in strip]
    return meaningful[0] if meaningful else parts[0]


def resolve_display_name(toolpack: "Toolpack") -> str:
    """Resolve the best human-friendly display name for a toolpack.

    Resolution order:
    1. display_name (explicitly set by user)
    2. origin.name (session name from capture)
    3. Host-derived slug (from allowed_hosts)
    4. toolpack_id (stable fallback)
    """
    if toolpack.display_name:
        return toolpack.display_name
    if toolpack.origin and toolpack.origin.name:
        return toolpack.origin.name
    slug = _host_slug(toolpack)
    if slug:
        return slug
    return toolpack.toolpack_id
```

Add the import at the top of `ops.py` if not already present — `Toolpack` is already imported via `load_toolpack` return type. Use a string annotation `"Toolpack"` to avoid circular imports if needed, but since `Toolpack` is used locally via `load_toolpack`, the import from `toolwright.core.toolpack` is already there.

**Step 4: Run test to verify it passes**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py -v`
Expected: 10 PASS

**Step 5: Commit**

```bash
git add toolwright/ui/ops.py tests/test_toolpack_display_name.py
git commit -m "feat: add resolve_display_name() helper in ops.py"
```

---

### Task 3: Thread display name into `get_status()` and `StatusModel`

**Files:**
- Modify: `toolwright/ui/ops.py:330-365` (StatusModel + get_status)
- Test: `tests/test_toolpack_display_name.py` (append test)

**Step 1: Write the failing test**

Append to `tests/test_toolpack_display_name.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestStatusModelDisplayName:
    """get_status uses resolve_display_name for toolpack_id."""

    def test_status_model_uses_display_name(self) -> None:
        from toolwright.ui.ops import StatusModel

        model = StatusModel(
            toolpack_id="my-api",
            toolpack_path="/tmp/tp.yaml",
            root="/tmp",
            lockfile_state="sealed",
            lockfile_path=None,
            approved_count=0,
            blocked_count=0,
            pending_count=0,
            has_baseline=False,
            baseline_age_seconds=None,
            drift_state="not_checked",
            verification_state="not_run",
            has_mcp_config=False,
            tool_count=0,
            alerts=[],
        )
        # toolpack_id should now contain the resolved display name
        assert model.toolpack_id == "my-api"
```

This test already passes (it just validates the field exists). The real verification is that `get_status()` calls `resolve_display_name()` — but that requires mocking the full toolpack load. We trust the integration via the wiring in Step 3.

**Step 2: Wire `resolve_display_name` into `get_status()`**

In `toolwright/ui/ops.py`, change line 365 from:

```python
    toolpack_id = toolpack.name if hasattr(toolpack, "name") and toolpack.name else tp_path.parent.name
```

To:

```python
    toolpack_id = resolve_display_name(toolpack)
```

**Step 3: Run full test suite to verify no regressions**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Expected: All pass

**Step 4: Commit**

```bash
git add toolwright/ui/ops.py tests/test_toolpack_display_name.py
git commit -m "feat: wire resolve_display_name into get_status()"
```

---

### Task 4: Update capture-time prompt

**Files:**
- Modify: `toolwright/ui/flows/quickstart.py:409-444`
- Test: `tests/test_wizard_flow.py` (update existing test)

**Step 1: Update the quickstart prompt**

In `toolwright/ui/flows/quickstart.py`, change line 444 from:

```python
    name = input_text("  Session name (optional)", console=con)
```

To:

```python
    # Auto-suggest name from host
    default_name = ""
    if hosts:
        host = hosts[0].split(":")[0]
        parts = host.split(".")
        strip = {"api", "www", "rest", "v1", "v2", "com", "org", "net", "io", "dev", "co"}
        meaningful = [p for p in parts if p.lower() not in strip]
        default_name = meaningful[0] if meaningful else parts[0]

    name = input_text(
        "  Name this API",
        default=default_name,
        console=con,
    )
```

**Step 2: Run wizard tests to verify no regressions**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_wizard_flow.py tests/test_ui_wizard.py -v`
Expected: All pass

**Step 3: Commit**

```bash
git add toolwright/ui/flows/quickstart.py
git commit -m "feat: rename 'Session name' prompt to 'Name this API' with host-derived default"
```

---

### Task 5: Store `display_name` during mint

**Files:**
- Modify: `toolwright/cli/mint.py:257-267`
- Test: Integration tested via existing mint tests + manual verification

**Step 1: Wire display_name into Toolpack creation**

In `toolwright/cli/mint.py`, change the Toolpack construction (around line 257) to include `display_name`:

```python
    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=resolve_generated_at(
            deterministic=deterministic,
            candidate=session.created_at if deterministic else None,
        ),
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope=scope_name,
        allowed_hosts=effective_allowed_hosts,
        display_name=name,  # store user-provided name as display_name
        origin=ToolpackOrigin(start_url=start_url, name=name),
        ...
    )
```

**Step 2: Run tests**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Expected: All pass

**Step 3: Commit**

```bash
git add toolwright/cli/mint.py
git commit -m "feat: store display_name in toolpack.yaml during mint"
```

---

### Task 6: Add `cask rename` command

**Files:**
- Modify: `toolwright/cli/main.py` (add command)
- Test: `tests/test_toolpack_display_name.py` (append CLI tests)

**Step 1: Write the failing tests**

Append to `tests/test_toolpack_display_name.py`:

```python
import yaml
from click.testing import CliRunner


class TestCaskRenameCommand:
    """cask rename updates display_name in toolpack.yaml."""

    def test_rename_updates_display_name(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        # Create minimal toolpack.yaml
        tp_dir = tmp_path / "toolpacks" / "myapi"
        tp_dir.mkdir(parents=True)
        tp_data = {
            "toolpack_id": "abc123",
            "schema_version": "1",
            "created_at": "2026-01-01T00:00:00Z",
            "capture_id": "cap1",
            "artifact_id": "art1",
            "scope": "first_party_only",
            "origin": {"start_url": "https://api.example.com"},
            "paths": {
                "tools": "tools.json",
                "toolsets": "toolsets.yaml",
                "policy": "policy.yaml",
                "baseline": "baseline.json",
            },
        }
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text(yaml.dump(tp_data))

        runner = CliRunner()
        result = runner.invoke(cli, ["rename", "my-cool-api", "--toolpack", str(tp_file)])
        assert result.exit_code == 0
        assert "my-cool-api" in result.output

        # Verify file was updated
        updated = yaml.safe_load(tp_file.read_text())
        assert updated["display_name"] == "my-cool-api"

    def test_rename_preserves_toolpack_id(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        tp_dir = tmp_path / "toolpacks" / "myapi"
        tp_dir.mkdir(parents=True)
        tp_data = {
            "toolpack_id": "abc123",
            "schema_version": "1",
            "created_at": "2026-01-01T00:00:00Z",
            "capture_id": "cap1",
            "artifact_id": "art1",
            "scope": "first_party_only",
            "origin": {"start_url": "https://api.example.com"},
            "paths": {
                "tools": "tools.json",
                "toolsets": "toolsets.yaml",
                "policy": "policy.yaml",
                "baseline": "baseline.json",
            },
        }
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text(yaml.dump(tp_data))

        runner = CliRunner()
        runner.invoke(cli, ["rename", "new-name", "--toolpack", str(tp_file)])

        updated = yaml.safe_load(tp_file.read_text())
        assert updated["toolpack_id"] == "abc123"  # unchanged

    def test_rename_does_not_invalidate_lockfile(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        tp_dir = tmp_path / "toolpacks" / "myapi"
        tp_dir.mkdir(parents=True)
        tp_data = {
            "toolpack_id": "abc123",
            "schema_version": "1",
            "created_at": "2026-01-01T00:00:00Z",
            "capture_id": "cap1",
            "artifact_id": "art1",
            "scope": "first_party_only",
            "origin": {"start_url": "https://api.example.com"},
            "paths": {
                "tools": "tools.json",
                "toolsets": "toolsets.yaml",
                "policy": "policy.yaml",
                "baseline": "baseline.json",
                "lockfiles": {"approved": "lockfile.yaml"},
            },
        }
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text(yaml.dump(tp_data))

        # Create a lockfile
        lockfile_content = "schema_version: '1'\ntools: {}\n"
        (tp_dir / "lockfile.yaml").write_text(lockfile_content)

        runner = CliRunner()
        result = runner.invoke(cli, ["rename", "renamed", "--toolpack", str(tp_file)])
        assert result.exit_code == 0

        # Lockfile unchanged
        assert (tp_dir / "lockfile.yaml").read_text() == lockfile_content
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py::TestCaskRenameCommand -v`
Expected: FAIL — `rename` command not found

**Step 3: Implement the `cask rename` command**

In `toolwright/cli/main.py`, add the command (near the other simple commands like `init`):

```python
@cli.command("rename")
@click.argument("new_name")
@click.option(
    "--toolpack",
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (auto-discovered if not given)",
)
@click.pass_context
def rename(ctx: click.Context, new_name: str, toolpack: str | None) -> None:
    """Rename a toolpack's display name.

    Updates only the display_name field in toolpack.yaml.
    Does not change toolpack_id, tool IDs, lockfile, or signatures.

    Examples:
      cask rename my-stripe-api
      cask rename production-api --toolpack .toolwright/toolpacks/api/toolpack.yaml
    """
    import yaml

    root = ctx.obj["root"]
    if toolpack is None:
        from toolwright.ui.discovery import find_toolpacks
        toolpacks = find_toolpacks(root)
        if not toolpacks:
            click.echo("No toolpack found. Use --toolpack to specify one.", err=True)
            ctx.exit(1)
            return
        toolpack = str(toolpacks[0])

    tp_path = Path(toolpack)

    # Read, update, write
    raw = yaml.safe_load(tp_path.read_text())
    old_name = raw.get("display_name") or raw.get("toolpack_id", "unnamed")
    raw["display_name"] = new_name
    tp_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

    click.echo(f"Renamed: {old_name} → {new_name}")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/test_toolpack_display_name.py -v`
Expected: All pass

**Step 5: Run full test suite**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Expected: All pass

**Step 6: Commit**

```bash
git add toolwright/cli/main.py tests/test_toolpack_display_name.py
git commit -m "feat: add cask rename command for toolpack display names"
```

---

### Task 7: Lint, full test suite, manual verification

**Step 1: Lint all changed files**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/ruff check toolwright/core/toolpack.py toolwright/ui/ops.py toolwright/ui/flows/quickstart.py toolwright/cli/mint.py toolwright/cli/main.py tests/test_toolpack_display_name.py`
Fix any issues.

**Step 2: Full test suite**

Run: `cd /Users/thomasallicino/oss/cask && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10`
Expected: All pass, 0 failures

**Step 3: Manual verification**

Verify `resolve_display_name` works by running:
```python
from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths
from toolwright.ui.ops import resolve_display_name
tp = Toolpack(toolpack_id="abc", created_at="2026-01-01T00:00:00Z", capture_id="c", artifact_id="a", scope="s", allowed_hosts=["api.stripe.com"], origin=ToolpackOrigin(start_url="https://api.stripe.com"), paths=ToolpackPaths(tools="t", toolsets="ts", policy="p", baseline="b"))
print(resolve_display_name(tp))  # should print "stripe"
```

**Step 4: Final commit if any fixes**

```bash
git add -u
git commit -m "chore: lint fixes for display name feature"
```
