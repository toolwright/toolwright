"""Policy and tool surface linting."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml

from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

SENSITIVE_TAGS = {"write", "delete", "money", "payment", "refund"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
REGEX_FIELDS = ("host_pattern", "path_pattern")


@dataclass(frozen=True)
class LintIssue:
    """A lint issue emitted by toolwright lint."""

    code: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "location": self.location,
            "message": self.message,
        }


def run_lint(
    *,
    toolpack_path: str | None,
    tools_path: str | None,
    policy_path: str | None,
    output_format: str,
    verbose: bool,
) -> None:
    """Lint tools/policy artifacts and fail on governance contract violations."""
    try:
        resolved_tools_path, resolved_policy_path = _resolve_artifact_paths(
            toolpack_path=toolpack_path,
            tools_path=tools_path,
            policy_path=policy_path,
        )
        tools_payload = _load_json(resolved_tools_path)
        policy_payload = _load_yaml(resolved_policy_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    issues: list[LintIssue] = []
    issues.extend(_lint_sensitive_actions(tools_payload))
    issues.extend(_lint_regex_justification(policy_payload))
    issues.extend(_lint_override_justification(policy_payload, tools_payload))
    issues = sorted(issues, key=lambda issue: (issue.code, issue.location, issue.message))

    if output_format == "json":
        payload = {"issues": [issue.as_dict() for issue in issues], "count": len(issues)}
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_text(issues)

    if issues:
        sys.exit(1)
    if verbose:
        click.echo(
            f"Lint scanned tools={resolved_tools_path} policy={resolved_policy_path}",
            err=True,
        )


def _resolve_artifact_paths(
    *,
    toolpack_path: str | None,
    tools_path: str | None,
    policy_path: str | None,
) -> tuple[Path, Path]:
    if toolpack_path:
        if tools_path or policy_path:
            raise ValueError("Use either --toolpack or --tools/--policy, not both")
        toolpack = load_toolpack(Path(toolpack_path))
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=Path(toolpack_path))
        return resolved.tools_path, resolved.policy_path

    if not tools_path or not policy_path:
        raise ValueError("Provide --toolpack, or both --tools and --policy")

    return Path(tools_path), Path(policy_path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return payload


def _lint_sensitive_actions(tools_payload: dict[str, Any]) -> list[LintIssue]:
    actions = tools_payload.get("actions")
    if not isinstance(actions, list):
        raise ValueError("tools.json must include an actions list")

    issues: list[LintIssue] = []
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        if not _is_sensitive_action(action):
            continue

        action_id = str(action.get("id") or action.get("name") or f"action[{idx}]")
        confirmation = str(action.get("confirmation_required", "")).strip().lower()
        guards = action.get("guards")
        has_explicit_guards = bool(guards) if isinstance(guards, list | dict) else False
        has_confirmation = confirmation not in {"", "none", "never"}
        has_rate_limit = _is_positive_number(action.get("rate_limit_per_minute"))

        if not (has_explicit_guards or has_confirmation or has_rate_limit):
            issues.append(
                LintIssue(
                    code="empty-guards",
                    location=f"actions[{idx}]({action_id})",
                    message=(
                        "Sensitive action (write/money/delete) is missing guardrails "
                        "(confirmation, non-empty guards, or positive rate limit)."
                    ),
                )
            )
    return issues


def _lint_regex_justification(policy_payload: dict[str, Any]) -> list[LintIssue]:
    issues: list[LintIssue] = []
    rules = policy_payload.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError("policy.yaml rules must be a list")

    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        match = rule.get("match") or {}
        if not isinstance(match, dict):
            continue
        for field in REGEX_FIELDS:
            pattern = match.get(field)
            if not _has_text(pattern):
                continue
            if not _has_rule_justification(rule):
                issues.append(
                    LintIssue(
                        code="regex-no-justification",
                        location=f"rules[{idx}].match.{field}",
                        message="Regex matcher requires justification in rule settings or description.",
                    )
                )
            elif not _is_valid_regex(str(pattern)):
                issues.append(
                    LintIssue(
                        code="regex-invalid",
                        location=f"rules[{idx}].match.{field}",
                        message="Regex matcher is invalid and will not compile.",
                    )
                )

    redact_patterns = policy_payload.get("redact_patterns") or []
    if not isinstance(redact_patterns, list):
        return issues

    justifications = policy_payload.get("redact_pattern_justifications")
    for idx, pattern in enumerate(redact_patterns):
        if not _has_text(pattern):
            continue
        if not _has_redact_pattern_justification(
            pattern=str(pattern),
            index=idx,
            justifications=justifications,
        ):
            issues.append(
                LintIssue(
                    code="regex-no-justification",
                    location=f"redact_patterns[{idx}]",
                    message="Regex redaction pattern requires justification.",
                )
            )
        elif not _is_valid_regex(str(pattern)):
            issues.append(
                LintIssue(
                    code="regex-invalid",
                    location=f"redact_patterns[{idx}]",
                    message="Regex redaction pattern is invalid and will not compile.",
                )
            )

    return issues


def _lint_override_justification(
    policy_payload: dict[str, Any],
    tools_payload: dict[str, Any],
) -> list[LintIssue]:
    issues: list[LintIssue] = []

    overrides = policy_payload.get("state_changing_overrides") or []
    if isinstance(overrides, list):
        for idx, override in enumerate(overrides):
            if not isinstance(override, dict):
                continue
            if _has_text(override.get("justification")):
                continue
            issues.append(
                LintIssue(
                    code="override-no-justification",
                    location=f"state_changing_overrides[{idx}]",
                    message="State-changing override requires a human justification.",
                )
            )

    actions = tools_payload.get("actions") or []
    if isinstance(actions, list):
        for idx, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            has_risk_override = "risk_override" in action or "risk_tier_override" in action
            if not has_risk_override:
                continue
            if _has_text(action.get("risk_override_justification")):
                continue
            action_id = str(action.get("id") or action.get("name") or f"action[{idx}]")
            issues.append(
                LintIssue(
                    code="override-no-justification",
                    location=f"actions[{idx}]({action_id})",
                    message="Risk override requires risk_override_justification.",
                )
            )

    return issues


def _is_sensitive_action(action: dict[str, Any]) -> bool:
    method = str(action.get("method", "")).upper()
    tags = action.get("tags") or []
    tags_lower = {
        str(tag).lower()
        for tag in tags
        if isinstance(tag, str)
    }
    risk_tier = str(action.get("risk_tier", "")).lower()
    return (
        method in WRITE_METHODS
        or bool(tags_lower.intersection(SENSITIVE_TAGS))
        or risk_tier in {"high", "critical"}
    )


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, int | float) and value > 0


def _has_rule_justification(rule: dict[str, Any]) -> bool:
    if _has_text(rule.get("description")):
        return True
    settings = rule.get("settings")
    return isinstance(settings, dict) and _has_text(settings.get("justification"))


def _has_redact_pattern_justification(
    *,
    pattern: str,
    index: int,
    justifications: Any,
) -> bool:
    if isinstance(justifications, dict):
        direct = justifications.get(pattern)
        return _has_text(direct)
    if isinstance(justifications, list):
        if index >= len(justifications):
            return False
        return _has_text(justifications[index])
    return False


def _is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _render_text(issues: list[LintIssue]) -> None:
    if not issues:
        click.echo("Lint passed: no issues found.")
        return

    click.echo(f"Lint failed: {len(issues)} issue(s) found.")
    for issue in issues:
        click.echo(f"- [{issue.code}] {issue.location}: {issue.message}")
