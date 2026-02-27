"""Pytest wrapper for Jira dogfood policy verification.

Runs the same checks as dogfood/jira/verify_policy.py but as pytest assertions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

JIRA_DIR = Path(__file__).parent.parent / "dogfood" / "jira"


@pytest.fixture(autouse=True)
def _skip_if_missing():
    """Skip all tests if Jira artifacts don't exist yet."""
    artifacts = JIRA_DIR / "artifact"
    if not (artifacts / "tools.json").exists() or not (artifacts / "policy.yaml").exists():
        pytest.skip("Jira artifacts not generated yet")


def _load_verify_module():
    """Import verify_policy from the dogfood/jira directory."""
    module_name = "jira_verify_policy"
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        return mod.verify_confirmation_coverage, mod.load_tools

    spec = importlib.util.spec_from_file_location(
        module_name, JIRA_DIR / "verify_policy.py"
    )
    if spec is None or spec.loader is None:
        pytest.skip("verify_policy.py not found")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod.verify_confirmation_coverage, mod.load_tools


class TestJiraPolicyVerification:
    """Test that Jira dogfood policy correctly gates state-changing operations."""

    def test_all_checks_pass(self):
        """The full verification suite should return zero errors."""
        verify_fn, _ = _load_verify_module()
        errors = verify_fn()
        assert errors == [], "Policy verification failed:\n" + "\n".join(f"  - {e}" for e in errors)

    def test_tool_count_in_range(self):
        """Should have 10-20 tools."""
        _, load_tools = _load_verify_module()
        tools = load_tools()
        assert 10 <= len(tools) <= 20, f"Expected 10-20 tools, got {len(tools)}"

    def test_post_tools_exist(self):
        """There should be at least 3 POST tools (create issue, comment, transition)."""
        _, load_tools = _load_verify_module()
        tools = load_tools()
        post_tools = [t for t in tools if t.get("method") == "POST"]
        assert len(post_tools) >= 3, f"Expected at least 3 POST tools, got {len(post_tools)}"

    def test_get_tools_exist(self):
        """There should be at least 5 GET tools."""
        _, load_tools = _load_verify_module()
        tools = load_tools()
        get_tools = [t for t in tools if t.get("method") == "GET"]
        assert len(get_tools) >= 5, f"Expected at least 5 GET tools, got {len(get_tools)}"
