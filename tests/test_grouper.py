"""Tests for tool group data model and grouping algorithm."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from toolwright.models.groups import ToolGroup, ToolGroupIndex
from toolwright.core.compile.grouper import (
    extract_semantic_segments,
    generate_tool_groups,
    filter_by_scope,
    suggest_group_name,
    load_groups_index,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(name: str, path: str, method: str = "GET") -> dict[str, Any]:
    """Create a minimal action dict for testing."""
    return {"name": name, "path": path, "method": method}


# ===========================================================================
# 1. Serialization round-trip
# ===========================================================================


class TestToolGroupSerialization:
    """ToolGroup and ToolGroupIndex serialization."""

    def test_tool_group_to_dict(self) -> None:
        group = ToolGroup(
            name="users",
            tools=["list_users", "get_user"],
            path_prefix="/users",
            description="User endpoints (2 tools)",
        )
        d = group.to_dict()
        assert d == {
            "name": "users",
            "tools": ["list_users", "get_user"],
            "path_prefix": "/users",
            "description": "User endpoints (2 tools)",
        }

    def test_tool_group_from_dict(self) -> None:
        data = {
            "name": "repos",
            "tools": ["list_repos"],
            "path_prefix": "/repos",
            "description": "Repos endpoints (1 tools)",
        }
        group = ToolGroup.from_dict(data)
        assert group.name == "repos"
        assert group.tools == ["list_repos"]
        assert group.path_prefix == "/repos"
        assert group.description == "Repos endpoints (1 tools)"

    def test_tool_group_from_dict_missing_description(self) -> None:
        data = {
            "name": "repos",
            "tools": ["list_repos"],
            "path_prefix": "/repos",
        }
        group = ToolGroup.from_dict(data)
        assert group.description is None

    def test_tool_group_roundtrip(self) -> None:
        original = ToolGroup(
            name="products",
            tools=["get_product", "list_products"],
            path_prefix="/products",
            description="Products endpoints (2 tools)",
        )
        restored = ToolGroup.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.tools == original.tools
        assert restored.path_prefix == original.path_prefix
        assert restored.description == original.description

    def test_tool_group_index_to_dict(self) -> None:
        index = ToolGroupIndex(
            groups=[
                ToolGroup(name="users", tools=["list_users"], path_prefix="/users"),
            ],
            ungrouped=["health_check"],
            generated_from="auto",
        )
        d = index.to_dict()
        assert len(d["groups"]) == 1
        assert d["ungrouped"] == ["health_check"]
        assert d["generated_from"] == "auto"

    def test_tool_group_index_from_dict(self) -> None:
        data = {
            "groups": [
                {
                    "name": "users",
                    "tools": ["list_users"],
                    "path_prefix": "/users",
                    "description": None,
                }
            ],
            "ungrouped": [],
            "generated_from": "manual",
        }
        index = ToolGroupIndex.from_dict(data)
        assert len(index.groups) == 1
        assert index.groups[0].name == "users"
        assert index.generated_from == "manual"

    def test_tool_group_index_json_roundtrip(self) -> None:
        index = ToolGroupIndex(
            groups=[
                ToolGroup(
                    name="orders",
                    tools=["create_order", "get_order"],
                    path_prefix="/orders",
                    description="Orders endpoints (2 tools)",
                ),
            ],
            ungrouped=["health"],
            generated_from="auto",
        )
        json_str = json.dumps(index.to_dict())
        restored = ToolGroupIndex.from_dict(json.loads(json_str))
        assert len(restored.groups) == 1
        assert restored.groups[0].name == "orders"
        assert restored.groups[0].tools == ["create_order", "get_order"]
        assert restored.ungrouped == ["health"]

    def test_tool_group_index_defaults(self) -> None:
        index = ToolGroupIndex()
        assert index.groups == []
        assert index.ungrouped == []
        assert index.generated_from == "auto"

    def test_tool_group_index_from_dict_missing_fields(self) -> None:
        index = ToolGroupIndex.from_dict({})
        assert index.groups == []
        assert index.ungrouped == []
        assert index.generated_from == "auto"


# ===========================================================================
# 2. Path cleaning (extract_semantic_segments)
# ===========================================================================


class TestExtractSemanticSegments:
    """Path cleaning strips noise from URL paths."""

    def test_simple_path(self) -> None:
        assert extract_semantic_segments("/users") == ["users"]

    def test_nested_path(self) -> None:
        assert extract_semantic_segments("/users/profile") == ["users", "profile"]

    def test_strips_api_prefix(self) -> None:
        assert extract_semantic_segments("/api/users") == ["users"]

    def test_strips_admin_prefix(self) -> None:
        assert extract_semantic_segments("/admin/settings") == ["settings"]

    def test_strips_rest_prefix(self) -> None:
        assert extract_semantic_segments("/rest/products") == ["products"]

    def test_strips_version_v1(self) -> None:
        assert extract_semantic_segments("/v1/orders") == ["orders"]

    def test_strips_version_v2(self) -> None:
        assert extract_semantic_segments("/api/v2/items") == ["items"]

    def test_strips_version_v3(self) -> None:
        assert extract_semantic_segments("/v3/resources") == ["resources"]

    def test_strips_year_month(self) -> None:
        # Azure-style date versions like 2026-01
        assert extract_semantic_segments("/2026-01/subscriptions") == ["subscriptions"]

    def test_strips_unstable(self) -> None:
        assert extract_semantic_segments("/unstable/rooms") == ["rooms"]

    def test_strips_stable(self) -> None:
        assert extract_semantic_segments("/stable/events") == ["events"]

    def test_strips_latest(self) -> None:
        assert extract_semantic_segments("/latest/builds") == ["builds"]

    def test_strips_path_params_curly(self) -> None:
        assert extract_semantic_segments("/users/{id}/posts") == ["users", "posts"]

    def test_strips_path_params_colon(self) -> None:
        assert extract_semantic_segments("/users/:id/posts") == ["users", "posts"]

    def test_strips_file_extensions_json(self) -> None:
        assert extract_semantic_segments("/data/export.json") == ["data", "export"]

    def test_strips_file_extensions_xml(self) -> None:
        assert extract_semantic_segments("/data/export.xml") == ["data", "export"]

    def test_strips_file_extensions_yaml(self) -> None:
        assert extract_semantic_segments("/config/schema.yaml") == ["config", "schema"]

    def test_case_insensitive_noise(self) -> None:
        assert extract_semantic_segments("/API/V1/Users") == ["users"]

    def test_empty_path(self) -> None:
        assert extract_semantic_segments("/") == []

    def test_all_noise(self) -> None:
        # Path that is all noise segments
        assert extract_semantic_segments("/api/v1/{id}") == []

    def test_combined_noise(self) -> None:
        result = extract_semantic_segments("/admin/api/v2/2025-06/products/{id}/reviews")
        assert result == ["products", "reviews"]

    def test_express_colon_params(self) -> None:
        assert extract_semantic_segments("/repos/:owner/:repo/issues") == [
            "repos",
            "issues",
        ]


# ===========================================================================
# 3. Primary grouping (first segment)
# ===========================================================================


class TestPrimaryGrouping:
    """generate_tool_groups groups by first semantic segment."""

    def test_single_group(self) -> None:
        actions = [
            _action("list_users", "/api/v1/users"),
            _action("get_user", "/api/v1/users/{id}"),
            _action("create_user", "/api/v1/users", "POST"),
        ]
        index = generate_tool_groups(actions)
        assert len(index.groups) == 1
        assert index.groups[0].name == "users"
        assert sorted(index.groups[0].tools) == [
            "create_user",
            "get_user",
            "list_users",
        ]

    def test_different_paths_different_groups(self) -> None:
        actions = [
            _action("list_users", "/users"),
            _action("list_orders", "/orders"),
            _action("list_products", "/products"),
        ]
        index = generate_tool_groups(actions)
        group_names = sorted(g.name for g in index.groups)
        assert group_names == ["orders", "products", "users"]

    def test_sub_resources_stay_in_parent(self) -> None:
        actions = [
            _action("list_users", "/users"),
            _action("get_user_profile", "/users/{id}/profile"),
            _action("get_user_settings", "/users/{id}/settings"),
        ]
        index = generate_tool_groups(actions)
        assert len(index.groups) == 1
        assert index.groups[0].name == "users"
        assert len(index.groups[0].tools) == 3

    def test_path_prefix_set_correctly(self) -> None:
        actions = [_action("list_repos", "/api/v2/repos")]
        index = generate_tool_groups(actions)
        assert index.groups[0].path_prefix == "/repos"


# ===========================================================================
# 4. Auto-split (groups > 80 tools)
# ===========================================================================


class TestAutoSplit:
    """Auto-split groups exceeding 80 tools."""

    def test_no_split_below_threshold(self) -> None:
        actions = [
            _action(f"tool_{i}", f"/repos/action_{i}") for i in range(79)
        ]
        index = generate_tool_groups(actions)
        # Should remain as a single group
        repo_groups = [g for g in index.groups if g.name.startswith("repos")]
        assert len(repo_groups) == 1

    def test_split_at_threshold(self) -> None:
        # Create 81 tools across two sub-resources under /repos
        actions = []
        for i in range(50):
            actions.append(_action(f"repos_issues_{i}", f"/repos/{{owner}}/issues/{i}"))
        for i in range(31):
            actions.append(_action(f"repos_pulls_{i}", f"/repos/{{owner}}/pulls/{i}"))
        index = generate_tool_groups(actions)
        # Should split into repos/issues and repos/pulls
        repo_groups = [g for g in index.groups if g.name.startswith("repos")]
        assert len(repo_groups) >= 2

    def test_recursive_split(self) -> None:
        # Create enough tools to trigger recursive splitting
        actions = []
        for i in range(90):
            actions.append(
                _action(
                    f"repos_issues_comments_{i}",
                    f"/repos/{{owner}}/issues/{{id}}/comments/{i}",
                )
            )
        index = generate_tool_groups(actions)
        # With only one sub-path, it should still produce a group
        assert len(index.groups) >= 1

    def test_catch_all_for_top_level(self) -> None:
        # Many tools at the same top-level segment with no sub-resources
        actions = [
            _action(f"repos_action_{i}", f"/repos/{i}") for i in range(85)
        ]
        index = generate_tool_groups(actions)
        # All tools should be in some group(s)
        total_tools = sum(len(g.tools) for g in index.groups) + len(index.ungrouped)
        assert total_tools == 85


# ===========================================================================
# 5. Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge cases for grouping."""

    def test_empty_actions(self) -> None:
        index = generate_tool_groups([])
        assert index.groups == []
        assert index.ungrouped == []

    def test_single_tool(self) -> None:
        actions = [_action("health", "/health")]
        index = generate_tool_groups(actions)
        total = sum(len(g.tools) for g in index.groups) + len(index.ungrouped)
        assert total == 1

    def test_ungrouped_when_no_segments(self) -> None:
        # Root path has no semantic segments
        actions = [_action("root_action", "/")]
        index = generate_tool_groups(actions)
        assert "root_action" in index.ungrouped

    def test_all_noise_path_goes_to_ungrouped(self) -> None:
        actions = [_action("noise_tool", "/api/v1/{id}")]
        index = generate_tool_groups(actions)
        assert "noise_tool" in index.ungrouped


# ===========================================================================
# 6. Output format
# ===========================================================================


class TestOutputFormat:
    """Output format checks."""

    def test_descriptions_generated(self) -> None:
        actions = [
            _action("list_users", "/users"),
            _action("get_user", "/users/{id}"),
        ]
        index = generate_tool_groups(actions)
        group = index.groups[0]
        assert group.description is not None
        assert "2 tools" in group.description

    def test_groups_alphabetically_sorted(self) -> None:
        actions = [
            _action("list_zebras", "/zebras"),
            _action("list_apples", "/apples"),
            _action("list_mangoes", "/mangoes"),
        ]
        index = generate_tool_groups(actions)
        names = [g.name for g in index.groups]
        assert names == sorted(names)

    def test_tools_within_groups_alphabetically_sorted(self) -> None:
        actions = [
            _action("z_users", "/users"),
            _action("a_users", "/users/{id}"),
            _action("m_users", "/users/{id}/profile"),
        ]
        index = generate_tool_groups(actions)
        group = index.groups[0]
        assert group.tools == sorted(group.tools)

    def test_generated_from_auto(self) -> None:
        index = generate_tool_groups([])
        assert index.generated_from == "auto"


# ===========================================================================
# 7. Scope filtering (filter_by_scope)
# ===========================================================================


class TestFilterByScope:
    """filter_by_scope filters actions by group names."""

    def _make_index_and_actions(self) -> tuple[ToolGroupIndex, list[dict[str, Any]]]:
        actions = [
            _action("list_users", "/users"),
            _action("get_user", "/users/{id}"),
            _action("list_repos", "/repos"),
            _action("get_repo", "/repos/{id}"),
            _action("list_issues", "/repos/{owner}/issues"),
            _action("health", "/health"),
        ]
        index = generate_tool_groups(actions)
        return index, actions

    def test_single_group(self) -> None:
        index, actions = self._make_index_and_actions()
        filtered = filter_by_scope(actions, "users", index)
        names = [a["name"] for a in filtered]
        assert "list_users" in names
        assert "get_user" in names
        assert "list_repos" not in names

    def test_multiple_groups(self) -> None:
        index, actions = self._make_index_and_actions()
        filtered = filter_by_scope(actions, "users,health", index)
        names = [a["name"] for a in filtered]
        assert "list_users" in names
        assert "health" in names
        assert "list_repos" not in names

    def test_prefix_matching(self) -> None:
        # "repos" should match "repos", "repos/issues", "repos/pulls" etc
        actions = [
            _action("list_repos", "/repos"),
            _action("get_repo", "/repos/{id}"),
        ]
        # Create auto-split scenario with repos sub-groups
        sub_actions = []
        for i in range(50):
            sub_actions.append(
                _action(f"repos_issues_{i}", f"/repos/{{owner}}/issues/{i}")
            )
        for i in range(40):
            sub_actions.append(
                _action(f"repos_pulls_{i}", f"/repos/{{owner}}/pulls/{i}")
            )
        all_actions = actions + sub_actions
        index = generate_tool_groups(all_actions)
        # "repos" prefix should match all repos-related groups
        filtered = filter_by_scope(all_actions, "repos", index)
        assert len(filtered) == len(all_actions)

    def test_unknown_group_raises_value_error(self) -> None:
        index, actions = self._make_index_and_actions()
        with pytest.raises(ValueError, match="Unknown"):
            filter_by_scope(actions, "nonexistent", index)


# ===========================================================================
# 8. Fuzzy suggestions (suggest_group_name)
# ===========================================================================


class TestFuzzySuggestions:
    """suggest_group_name finds close matches."""

    def test_close_match_found(self) -> None:
        available = ["users", "repos", "issues", "pulls"]
        result = suggest_group_name("usrs", available)
        assert result == "users"

    def test_exact_match(self) -> None:
        available = ["users", "repos"]
        result = suggest_group_name("users", available)
        assert result == "users"

    def test_no_match_returns_none(self) -> None:
        available = ["users", "repos"]
        result = suggest_group_name("zzzzz", available)
        assert result is None

    def test_prefix_match(self) -> None:
        available = ["users", "repos", "issues"]
        result = suggest_group_name("use", available)
        assert result == "users"

    def test_single_char_edit(self) -> None:
        available = ["products", "orders"]
        result = suggest_group_name("produts", available)
        assert result == "products"


# ===========================================================================
# 9. load_groups_index
# ===========================================================================


class TestLoadGroupsIndex:
    """load_groups_index reads from JSON files."""

    def test_load_valid_file(self) -> None:
        index = ToolGroupIndex(
            groups=[
                ToolGroup(
                    name="users",
                    tools=["list_users"],
                    path_prefix="/users",
                    description="Users endpoints (1 tools)",
                ),
            ],
            ungrouped=[],
            generated_from="auto",
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(index.to_dict(), f)
            f.flush()
            loaded = load_groups_index(Path(f.name))
        assert loaded is not None
        assert len(loaded.groups) == 1
        assert loaded.groups[0].name == "users"

    def test_load_none_path(self) -> None:
        result = load_groups_index(None)
        assert result is None

    def test_load_nonexistent_file(self) -> None:
        result = load_groups_index(Path("/tmp/nonexistent_groups_12345.json"))
        assert result is None
