"""Tests for get_status() tool_count — verifies correct counting from tools.json.

Bug: get_status() checks isinstance(tools_data, list) but tools.json is a dict
with an "actions" key, so tool_count is always 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestStatusToolCount:
    """get_status() should correctly count tools from both dict and list formats."""

    def test_status_counts_tools_from_dict_format(self, tmp_path: Path) -> None:
        """tools.json as {"actions": [...]} should yield correct tool_count."""
        from toolwright.ui.ops import get_status

        # Write a dict-format tools.json with 3 actions
        tools_path = tmp_path / "tools.json"
        tools_data = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Test API",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {"id": "get_users", "name": "get_users"},
                {"id": "create_user", "name": "create_user"},
                {"id": "delete_user", "name": "delete_user"},
            ],
        }
        tools_path.write_text(json.dumps(tools_data))

        mock_resolved = MagicMock()
        mock_resolved.tools_path = tools_path
        mock_resolved.toolsets_path = tmp_path / "toolsets.yaml"
        mock_resolved.policy_path = tmp_path / "policy.yaml"
        mock_resolved.baseline_path = tmp_path / "baseline.json"
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = None

        mock_toolpack = MagicMock()
        mock_toolpack.display_name = "test-api"
        mock_toolpack.origin = None
        mock_toolpack.allowed_hosts = ["api.example.com"]
        mock_toolpack.toolpack_id = "test-api"

        with (
            patch("toolwright.ui.ops.load_toolpack", return_value=mock_toolpack),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            status = get_status(str(tmp_path / "toolpack.yaml"))

        assert status.tool_count == 3, (
            f"Expected tool_count=3 for dict-format tools.json, got {status.tool_count}"
        )

    def test_status_counts_tools_from_list_format(self, tmp_path: Path) -> None:
        """tools.json as [...] (legacy list format) should yield correct tool_count."""
        from toolwright.ui.ops import get_status

        # Write a legacy list-format tools.json with 2 items
        tools_path = tmp_path / "tools.json"
        tools_data = [
            {"id": "get_items", "name": "get_items"},
            {"id": "post_items", "name": "post_items"},
        ]
        tools_path.write_text(json.dumps(tools_data))

        mock_resolved = MagicMock()
        mock_resolved.tools_path = tools_path
        mock_resolved.toolsets_path = tmp_path / "toolsets.yaml"
        mock_resolved.policy_path = tmp_path / "policy.yaml"
        mock_resolved.baseline_path = tmp_path / "baseline.json"
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = None

        mock_toolpack = MagicMock()
        mock_toolpack.display_name = "legacy-api"
        mock_toolpack.origin = None
        mock_toolpack.allowed_hosts = []
        mock_toolpack.toolpack_id = "legacy-api"

        with (
            patch("toolwright.ui.ops.load_toolpack", return_value=mock_toolpack),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            status = get_status(str(tmp_path / "toolpack.yaml"))

        assert status.tool_count == 2, (
            f"Expected tool_count=2 for list-format tools.json, got {status.tool_count}"
        )

    def test_status_tool_count_zero_when_no_tools_file(self, tmp_path: Path) -> None:
        """When tools.json does not exist, tool_count should be 0."""
        from toolwright.ui.ops import get_status

        mock_resolved = MagicMock()
        mock_resolved.tools_path = tmp_path / "nonexistent_tools.json"
        mock_resolved.toolsets_path = tmp_path / "toolsets.yaml"
        mock_resolved.policy_path = tmp_path / "policy.yaml"
        mock_resolved.baseline_path = tmp_path / "baseline.json"
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = None

        mock_toolpack = MagicMock()
        mock_toolpack.display_name = "empty-api"
        mock_toolpack.origin = None
        mock_toolpack.allowed_hosts = []
        mock_toolpack.toolpack_id = "empty-api"

        with (
            patch("toolwright.ui.ops.load_toolpack", return_value=mock_toolpack),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            status = get_status(str(tmp_path / "toolpack.yaml"))

        assert status.tool_count == 0

    def test_status_tool_count_zero_for_empty_actions(self, tmp_path: Path) -> None:
        """Dict format with empty actions list should yield tool_count=0."""
        from toolwright.ui.ops import get_status

        tools_path = tmp_path / "tools.json"
        tools_data = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Empty API",
            "allowed_hosts": [],
            "actions": [],
        }
        tools_path.write_text(json.dumps(tools_data))

        mock_resolved = MagicMock()
        mock_resolved.tools_path = tools_path
        mock_resolved.toolsets_path = tmp_path / "toolsets.yaml"
        mock_resolved.policy_path = tmp_path / "policy.yaml"
        mock_resolved.baseline_path = tmp_path / "baseline.json"
        mock_resolved.approved_lockfile_path = None
        mock_resolved.pending_lockfile_path = None

        mock_toolpack = MagicMock()
        mock_toolpack.display_name = "empty-api"
        mock_toolpack.origin = None
        mock_toolpack.allowed_hosts = []
        mock_toolpack.toolpack_id = "empty-api"

        with (
            patch("toolwright.ui.ops.load_toolpack", return_value=mock_toolpack),
            patch("toolwright.ui.ops.resolve_toolpack_paths", return_value=mock_resolved),
        ):
            status = get_status(str(tmp_path / "toolpack.yaml"))

        assert status.tool_count == 0
