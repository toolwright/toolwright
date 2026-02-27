"""Tests for tag-based scope syntax in parser and builtins."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from toolwright.core.scope.parser import parse_scope_dict, parse_scope_file
from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import FilterOperator


def _ep(tags: list[str], method: str = "GET", path: str = "/api/v1/items") -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
        tags=tags,
    )


class TestTagShorthandParsing:
    """Test that tags shorthand in scope YAML expands to ScopeFilter rules."""

    def test_tags_include_expands_to_rules(self):
        data = {
            "name": "commerce_tools",
            "tags": {
                "include": ["commerce", "products"],
            },
        }
        scope = parse_scope_dict(data)
        assert scope.name == "commerce_tools"
        # Should have an include rule with CONTAINS filter on tags
        include_rules = [r for r in scope.rules if r.include]
        assert len(include_rules) >= 1
        # At least one filter should use tags field
        tag_filters = [
            f
            for r in include_rules
            for f in r.filters
            if f.field == "tags"
        ]
        assert len(tag_filters) >= 2  # One per included tag

    def test_tags_exclude_expands_to_rules(self):
        data = {
            "name": "no_auth",
            "tags": {
                "exclude": ["auth", "admin"],
            },
        }
        scope = parse_scope_dict(data)
        exclude_rules = [r for r in scope.rules if not r.include]
        assert len(exclude_rules) >= 1
        tag_filters = [
            f
            for r in exclude_rules
            for f in r.filters
            if f.field == "tags"
        ]
        assert len(tag_filters) >= 2

    def test_tags_include_and_exclude(self):
        data = {
            "name": "commerce_no_admin",
            "tags": {
                "include": ["commerce"],
                "exclude": ["admin", "auth"],
            },
        }
        scope = parse_scope_dict(data)
        include_rules = [r for r in scope.rules if r.include]
        exclude_rules = [r for r in scope.rules if not r.include]
        assert len(include_rules) >= 1
        assert len(exclude_rules) >= 1

    def test_tags_coexist_with_explicit_rules(self):
        data = {
            "name": "mixed",
            "tags": {
                "include": ["commerce"],
            },
            "rules": [
                {
                    "name": "get_only",
                    "include": False,
                    "filters": [
                        {"field": "method", "operator": "not_equals", "value": "GET"},
                    ],
                },
            ],
        }
        scope = parse_scope_dict(data)
        # Should have both the explicit rule and the tag-generated rules
        assert len(scope.rules) >= 2


class TestTagScopeFiltering:
    """Test that tag-based scopes correctly filter endpoints."""

    def test_include_tag_matches(self):
        data = {
            "name": "commerce_only",
            "tags": {"include": ["commerce"]},
        }
        scope = parse_scope_dict(data)
        ep_commerce = _ep(tags=["commerce", "read"])
        ep_users = _ep(tags=["users", "read"])

        # Commerce endpoint should match an include rule
        include_rules = [r for r in scope.rules if r.include]
        assert any(
            all(f.evaluate(ep_commerce) for f in rule.filters)
            for rule in include_rules
        )
        # Users endpoint should NOT match include rules (no commerce tag)
        assert not any(
            all(f.evaluate(ep_users) for f in rule.filters)
            for rule in include_rules
        )

    def test_exclude_tag_matches(self):
        data = {
            "name": "no_auth",
            "tags": {"exclude": ["auth"]},
        }
        scope = parse_scope_dict(data)
        ep_auth = _ep(tags=["auth", "write"])
        ep_normal = _ep(tags=["commerce", "read"])

        exclude_rules = [r for r in scope.rules if not r.include]
        # Auth endpoint should match the exclude rule
        assert any(
            all(f.evaluate(ep_auth) for f in rule.filters)
            for rule in exclude_rules
        )
        # Normal endpoint should NOT match exclude rules
        assert not any(
            all(f.evaluate(ep_normal) for f in rule.filters)
            for rule in exclude_rules
        )


class TestTagScopeYAMLFile:
    """Test parsing tag-based scopes from YAML files."""

    def test_parse_from_file(self):
        scope_data = {
            "name": "test_tag_scope",
            "tags": {
                "include": ["commerce", "products"],
                "exclude": ["auth"],
            },
        }
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", delete=False
        ) as f:
            yaml.dump(scope_data, f)
            tmp_path = f.name

        try:
            scope = parse_scope_file(tmp_path)
            assert scope.name == "test_tag_scope"
            assert len(scope.rules) >= 3  # 2 include + 1 exclude
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestTagScopeOperators:
    """Verify that generated filters use CONTAINS/NOT_CONTAINS operators."""

    def test_include_uses_contains(self):
        data = {
            "name": "test",
            "tags": {"include": ["commerce"]},
        }
        scope = parse_scope_dict(data)
        include_filters = [
            f
            for r in scope.rules
            if r.include
            for f in r.filters
        ]
        assert any(f.operator == FilterOperator.CONTAINS for f in include_filters)

    def test_exclude_uses_contains(self):
        """Exclude rules use CONTAINS (on an exclude rule, not NOT_CONTAINS)."""
        data = {
            "name": "test",
            "tags": {"exclude": ["auth"]},
        }
        scope = parse_scope_dict(data)
        exclude_filters = [
            f
            for r in scope.rules
            if not r.include
            for f in r.filters
        ]
        # Exclude rules use include=False with CONTAINS filter
        assert any(f.operator == FilterOperator.CONTAINS for f in exclude_filters)
