"""Tests for toolwright lint command."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


def _write_json(path: Path, payload: dict) -> None:  # noqa: ANN001
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_yaml(path: Path, payload: dict) -> None:  # noqa: ANN001
    path.write_text(yaml.safe_dump(payload, sort_keys=False))


def test_lint_fails_on_empty_guards_regex_and_override_justification(tmp_path: Path) -> None:
    tools_path = tmp_path / "tools.json"
    policy_path = tmp_path / "policy.yaml"

    _write_json(
        tools_path,
        {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Lint Fixtures",
            "actions": [
                {
                    "id": "delete_payment_method",
                    "tool_id": "sig_delete_payment_method",
                    "name": "delete_payment_method",
                    "description": "Delete a payment method",
                    "endpoint_id": "ep_delete_payment_method",
                    "signature_id": "sig_delete_payment_method",
                    "method": "DELETE",
                    "path": "/payments/methods/{id}",
                    "host": "api.example.com",
                    "input_schema": {"type": "object", "properties": {}},
                    "risk_tier": "high",
                    "confirmation_required": "never",
                    "rate_limit_per_minute": 0,
                    "tags": ["delete", "money"],
                }
            ],
        },
    )

    _write_yaml(
        policy_path,
        {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Lint Policy",
            "default_action": "deny",
            "redact_patterns": [r"bearer\\s+[A-Za-z0-9\\-_.]+"],
            "rules": [
                {
                    "id": "deny_admin",
                    "name": "Deny admin",
                    "type": "deny",
                    "priority": 100,
                    "match": {"path_pattern": ".*/admin.*"},
                }
            ],
            "state_changing_overrides": [
                {
                    "tool_id": "sig_delete_payment_method",
                    "state_changing": True,
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--tools", str(tools_path), "--policy", str(policy_path)],
    )
    assert result.exit_code == 1
    assert "empty-guards" in result.output
    assert "regex-no-justification" in result.output
    assert "override-no-justification" in result.output


def test_lint_passes_with_justifications_and_guards(tmp_path: Path) -> None:
    tools_path = tmp_path / "tools.json"
    policy_path = tmp_path / "policy.yaml"

    _write_json(
        tools_path,
        {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Lint Fixtures",
            "actions": [
                {
                    "id": "delete_payment_method",
                    "tool_id": "sig_delete_payment_method",
                    "name": "delete_payment_method",
                    "description": "Delete a payment method",
                    "endpoint_id": "ep_delete_payment_method",
                    "signature_id": "sig_delete_payment_method",
                    "method": "DELETE",
                    "path": "/payments/methods/{id}",
                    "host": "api.example.com",
                    "input_schema": {"type": "object", "properties": {}},
                    "risk_tier": "high",
                    "confirmation_required": "always",
                    "rate_limit_per_minute": 5,
                    "tags": ["delete", "money"],
                }
            ],
        },
    )

    _write_yaml(
        policy_path,
        {
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Lint Policy",
            "default_action": "deny",
            "redact_patterns": [r"bearer\\s+[A-Za-z0-9\\-_.]+"],
            "redact_pattern_justifications": {
                r"bearer\\s+[A-Za-z0-9\\-_.]+": "Redact bearer tokens from logs."
            },
            "rules": [
                {
                    "id": "deny_admin",
                    "name": "Deny admin",
                    "description": "Protect admin endpoints.",
                    "type": "deny",
                    "priority": 100,
                    "match": {"path_pattern": ".*/admin.*"},
                    "settings": {"justification": "Administrative operations are blocked by default."},
                }
            ],
            "state_changing_overrides": [
                {
                    "tool_id": "sig_delete_payment_method",
                    "state_changing": True,
                    "justification": "Delete payment method is always state-changing.",
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--tools", str(tools_path), "--policy", str(policy_path)],
    )
    assert result.exit_code == 0
    assert "Lint passed" in result.output


def test_lint_can_resolve_artifacts_from_toolpack(tmp_path: Path) -> None:
    toolpack_path = write_demo_toolpack(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["lint", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
