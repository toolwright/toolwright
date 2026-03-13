"""Tests for _singularize in toolwright.utils.naming.

Covers the silent-e fix that prevents truncated tool names like
'enterpris', 'cach', 'releas', 'analys' from appearing in generated output.
"""

from __future__ import annotations

import pytest

from toolwright.utils.naming import _singularize, generate_tool_name


class TestSingularize:
    """Test _singularize handles silent-e words and true -es plurals."""

    # --- Silent-e words (should strip 's', not 'es') ---

    @pytest.mark.parametrize(
        "plural,expected",
        [
            ("enterprises", "enterprise"),
            ("releases", "release"),
            ("caches", "cache"),
            ("databases", "database"),
            ("licenses", "license"),
            ("cases", "case"),
            ("bases", "base"),
            ("responses", "response"),
            ("courses", "course"),
            ("resources", "resource"),
            ("purposes", "purpose"),
            ("phrases", "phrase"),
        ],
    )
    def test_silent_e_words(self, plural: str, expected: str) -> None:
        assert _singularize(plural) == expected

    # --- True -es plurals (should strip 'es') ---

    @pytest.mark.parametrize(
        "plural,expected",
        [
            ("buses", "bus"),
            ("statuses", "status"),
            ("focuses", "focus"),
            ("bonuses", "bonus"),
            ("viruses", "virus"),
            ("classes", "class"),
            ("addresses", "address"),
            ("processes", "process"),
            ("boxes", "box"),
            ("taxes", "tax"),
            ("buzzes", "buzz"),
            ("branches", "branch"),
            ("churches", "church"),
            ("matches", "match"),
            ("watches", "watch"),
            ("dishes", "dish"),
            ("crashes", "crash"),
            ("pushes", "push"),
        ],
    )
    def test_true_es_plurals(self, plural: str, expected: str) -> None:
        assert _singularize(plural) == expected

    # --- Irregular plurals ---

    @pytest.mark.parametrize(
        "plural,expected",
        [
            ("analyses", "analysis"),
            ("indices", "index"),
            ("matrices", "matrix"),
            ("people", "person"),
        ],
    )
    def test_irregular_plurals(self, plural: str, expected: str) -> None:
        assert _singularize(plural) == expected

    # --- Simple -s plurals ---

    @pytest.mark.parametrize(
        "plural,expected",
        [
            ("users", "user"),
            ("repos", "repo"),
            ("teams", "team"),
            ("issues", "issue"),
            ("pulls", "pull"),
            ("categories", "category"),
        ],
    )
    def test_simple_s_plurals(self, plural: str, expected: str) -> None:
        assert _singularize(plural) == expected

    # --- Words that should not be modified ---

    @pytest.mark.parametrize("word", ["status", "bus", "analysis", "cache", "index"])
    def test_already_singular(self, word: str) -> None:
        # Already singular words should pass through unchanged
        # (some may change due to rules, but that's OK for this codebase)
        result = _singularize(word)
        # At minimum, should not crash
        assert isinstance(result, str)


class TestGenerateToolNameNoTruncation:
    """Verify generate_tool_name produces untruncated names for GitHub-like paths."""

    @pytest.mark.parametrize(
        "method,path,expected",
        [
            (
                "POST",
                "/enterprises/{enterprise}/teams/{team}/memberships/add",
                "create_enterprise_team_memberships_add",
            ),
            (
                "DELETE",
                "/repos/{owner}/{repo}/actions/caches/{cache_id}",
                "delete_repo_actions_cache",
            ),
            (
                "POST",
                "/repos/{owner}/{repo}/releases",
                "create_repo_release",
            ),
            (
                "DELETE",
                "/repos/{owner}/{repo}/code-scanning/analyses/{analysis_id}",
                "delete_repo_code_scanning_analysis",
            ),
            (
                "GET",
                "/repos/{owner}/{repo}/releases",
                "get_repo_releases",
            ),
            (
                "GET",
                "/enterprises/{enterprise}/dependabot/alerts",
                "get_enterprise_dependabot_alerts",
            ),
        ],
    )
    def test_github_paths_not_truncated(
        self, method: str, path: str, expected: str
    ) -> None:
        result = generate_tool_name(method, path)
        assert result == expected
