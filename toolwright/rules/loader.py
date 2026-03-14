"""Load and apply bundled rule templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from toolwright.models.rule import BehavioralRule, RuleStatus

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def list_templates() -> list[dict[str, Any]]:
    """Return metadata for all bundled templates."""
    results = []
    for path in sorted(_TEMPLATES_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        results.append({
            "name": data["name"],
            "description": data.get("description", ""),
            "rule_count": len(data.get("rules", [])),
        })
    return results


def load_template(name: str) -> dict[str, Any]:
    """Load a template by name. Raises ValueError if not found."""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in sorted(_TEMPLATES_DIR.glob("*.yaml"))]
        raise ValueError(
            f"Unknown rule template: {name}. "
            f"Available: {', '.join(available)}"
        )
    with open(path) as f:
        return yaml.safe_load(f)


def apply_template(
    name: str,
    *,
    rules_path: Path,
    activate: bool = False,
) -> list[BehavioralRule]:
    """Load a template and create rules in the rules JSON file.

    Returns the list of newly created rules. Rules that already exist
    (matched by template name + rule name prefix) are silently skipped.
    Use ``apply_template_verbose`` if you need the skip count.
    """
    created, _ = apply_template_verbose(
        name, rules_path=rules_path, activate=activate
    )
    return created


def apply_template_verbose(
    name: str,
    *,
    rules_path: Path,
    activate: bool = False,
) -> tuple[list[BehavioralRule], int]:
    """Load a template and create rules, returning (created, skipped_count)."""
    template = load_template(name)
    status = RuleStatus.ACTIVE if activate else RuleStatus.DRAFT

    # Load existing rules to check for duplicates
    existing: list[dict[str, Any]] = []
    if rules_path.exists():
        raw = rules_path.read_text()
        if raw.strip():
            existing = json.loads(raw)

    # Build set of existing template+rule prefixes (ignoring UUID suffix)
    existing_prefixes: set[str] = set()
    for rule_dict in existing:
        rule_id = rule_dict.get("rule_id", "")
        # Template rule IDs are: tmpl-{template}-{rule_name}-{uuid6}
        # Strip the last segment (UUID) to get the logical identity
        parts = rule_id.rsplit("-", 1)
        if len(parts) == 2 and rule_id.startswith(f"tmpl-{name}-"):
            existing_prefixes.add(parts[0])

    created: list[BehavioralRule] = []
    skipped = 0
    for rule_def in template.get("rules", []):
        logical_prefix = f"tmpl-{name}-{rule_def['name']}"
        if logical_prefix in existing_prefixes:
            # Rule already exists from this template — skip
            skipped += 1
            continue

        rule = BehavioralRule(
            rule_id=f"tmpl-{name}-{rule_def['name']}-{uuid4().hex[:6]}",
            kind=rule_def["kind"],
            description=rule_def["description"],
            status=status,
            priority=rule_def.get("priority", 100),
            target_tool_ids=rule_def.get("target_tool_ids", []),
            target_name_patterns=rule_def.get("target_name_patterns", []),
            target_methods=rule_def.get("target_methods", []),
            target_hosts=rule_def.get("target_hosts", []),
            match=rule_def.get("match", "all"),
            config=rule_def["config"],
            created_by=f"template:{name}",
        )
        created.append(rule)

    for rule in created:
        existing.append(json.loads(rule.model_dump_json()))

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(existing, indent=2, default=str))

    return created, skipped
