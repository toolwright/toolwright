"""Tests for toolpack display_name field and resolution."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner


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
        from toolwright.core.toolpack import Toolpack

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


class TestResolveDisplayName:
    """resolve_display_name returns the best human-friendly name."""

    def _make_toolpack(self, **overrides):
        from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths

        defaults = {
            "toolpack_id": "abc123",
            "created_at": "2026-01-01T00:00:00Z",
            "capture_id": "cap1",
            "artifact_id": "art1",
            "scope": "first_party_only",
            "origin": ToolpackOrigin(start_url="https://api.example.com"),
            "paths": ToolpackPaths(
                tools="tools.json",
                toolsets="toolsets.yaml",
                policy="policy.yaml",
                baseline="baseline.json",
            ),
        }
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
        assert model.toolpack_id == "my-api"



class TestToolwrightRenameCommand:
    """toolwright rename updates display_name in toolpack.yaml."""

    def _make_toolpack_file(self, tmp_path: Path) -> Path:
        """Create a minimal toolpack.yaml for testing."""
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
        return tp_file

    def test_rename_updates_display_name(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        tp_file = self._make_toolpack_file(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["rename", "my-cool-api", "--toolpack", str(tp_file)])
        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "my-cool-api" in result.output

        # Verify file was updated
        updated = yaml.safe_load(tp_file.read_text())
        assert updated["display_name"] == "my-cool-api"

    def test_rename_preserves_toolpack_id(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        tp_file = self._make_toolpack_file(tmp_path)

        runner = CliRunner()
        runner.invoke(cli, ["rename", "new-name", "--toolpack", str(tp_file)])

        updated = yaml.safe_load(tp_file.read_text())
        assert updated["toolpack_id"] == "abc123"  # unchanged

    def test_rename_does_not_invalidate_lockfile(self, tmp_path: Path) -> None:
        from toolwright.cli.main import cli

        tp_file = self._make_toolpack_file(tmp_path)

        # Create a lockfile next to toolpack
        lockfile_content = "schema_version: '1'\ntools: {}\n"
        (tp_file.parent / "lockfile.yaml").write_text(lockfile_content)

        runner = CliRunner()
        result = runner.invoke(cli, ["rename", "renamed", "--toolpack", str(tp_file)])
        assert result.exit_code == 0

        # Lockfile unchanged
        assert (tp_file.parent / "lockfile.yaml").read_text() == lockfile_content
