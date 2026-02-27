#!/usr/bin/env python3
"""Verify Jira dogfood policy: all state-changing tools require confirmation.

Loads artifact/tools.json and artifact/policy.yaml and asserts:
1. Every tool with method in (POST, PUT, PATCH, DELETE) is matched by a
   policy rule with type=confirm
2. GET-only tools are NOT matched by confirmation rules
3. Total tool count is in expected range

Can be run standalone or via pytest.

Usage:
    python3 dogfood/jira/verify_policy.py
    pytest tests/test_jira_policy_verification.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ARTIFACT_DIR = Path(__file__).parent / "artifact"
TOOLS_PATH = ARTIFACT_DIR / "tools.json"
POLICY_PATH = ARTIFACT_DIR / "policy.yaml"

STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXPECTED_TOOL_COUNT_MIN = 10
EXPECTED_TOOL_COUNT_MAX = 20


def load_tools() -> list[dict]:
    """Load tools from tools.json."""
    data = json.loads(TOOLS_PATH.read_text())
    return data.get("actions", []) if isinstance(data, dict) else data


def load_policy() -> dict:
    """Load policy from policy.yaml."""
    return yaml.safe_load(POLICY_PATH.read_text())


def get_confirmation_rules(policy: dict) -> list[dict]:
    """Extract policy rules that require confirmation (type=confirm)."""
    return [r for r in policy.get("rules", []) if r.get("type") == "confirm"]


def tool_matches_rule(tool: dict, rule: dict) -> bool:
    """Check if a tool is matched by a policy rule."""
    match = rule.get("match", {})

    # Check method match
    rule_methods = match.get("methods", [])
    if rule_methods:
        tool_method = tool.get("method", "")
        if tool_method not in rule_methods:
            return False

    # Check path pattern match (if specified)
    path_pattern = match.get("path_pattern")
    if path_pattern:
        tool_path = tool.get("path", "")
        if not re.search(path_pattern, tool_path):
            return False

    # Check host match (if specified)
    rule_hosts = match.get("hosts", [])
    if rule_hosts:
        tool_host = tool.get("host", "")
        if tool_host not in rule_hosts:
            return False

    return True


def verify_confirmation_coverage() -> list[str]:
    """Verify all state-changing tools are covered by confirmation rules.

    Returns list of error strings. Empty = all checks pass.
    """
    tools = load_tools()
    policy = load_policy()
    confirm_rules = get_confirmation_rules(policy)
    errors: list[str] = []

    # Check tool count
    if not (EXPECTED_TOOL_COUNT_MIN <= len(tools) <= EXPECTED_TOOL_COUNT_MAX):
        errors.append(
            f"Tool count {len(tools)} outside expected range "
            f"[{EXPECTED_TOOL_COUNT_MIN}, {EXPECTED_TOOL_COUNT_MAX}]"
        )

    # Check each tool
    state_changing_tools = [t for t in tools if t.get("method") in STATE_CHANGING_METHODS]
    get_tools = [t for t in tools if t.get("method") == "GET"]

    # All state-changing tools must match at least one confirm rule
    for tool in state_changing_tools:
        matched = any(tool_matches_rule(tool, r) for r in confirm_rules)
        if not matched:
            errors.append(
                f"State-changing tool '{tool.get('name')}' (method={tool.get('method')}) "
                f"is NOT matched by any confirmation rule"
            )

    # GET tools should NOT match method-based confirmation rules
    # (they may match path-based PII rules, which is acceptable)
    method_confirm_rules = [
        r for r in confirm_rules if r.get("match", {}).get("methods") and not r.get("match", {}).get("path_pattern")
    ]
    for tool in get_tools:
        for rule in method_confirm_rules:
            if tool_matches_rule(tool, rule):
                errors.append(
                    f"GET tool '{tool.get('name')}' matched method-based confirmation "
                    f"rule '{rule.get('id')}' — only state-changing tools should match"
                )

    return errors


def main() -> int:
    """Run verification and print results."""
    tools = load_tools()
    policy = load_policy()
    confirm_rules = get_confirmation_rules(policy)

    print(f"Tools: {len(tools)}")
    print(f"Confirmation rules: {len(confirm_rules)}")

    state_changing = [t for t in tools if t.get("method") in STATE_CHANGING_METHODS]
    get_only = [t for t in tools if t.get("method") == "GET"]
    print(f"State-changing tools: {len(state_changing)}")
    print(f"GET tools: {len(get_only)}")
    print()

    errors = verify_confirmation_coverage()

    if errors:
        print(f"FAIL: {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS: All state-changing tools require confirmation.")
    print("PASS: No GET tools matched by method-based confirmation rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
