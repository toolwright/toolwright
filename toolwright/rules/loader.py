"""Load and apply bundled rule templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from toolwright.models.rule import BehavioralRule, RuleStatus

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Rule template must contain a mapping: {path}")
    return dict(data)


def list_templates() -> list[dict[str, Any]]:
    """Return metadata for all bundled templates."""
    results: list[dict[str, Any]] = []
    for path in sorted(_TEMPLATES_DIR.glob("*.yaml")):
        data = _load_yaml_dict(path)
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
    return _load_yaml_dict(path)


def apply_template(
    name: str,
    *,
    rules_path: Path,
    activate: bool = False,
) -> list[BehavioralRule]:
    """Load a template and create rules in the rules JSON file."""
    template = load_template(name)
    status = RuleStatus.ACTIVE if activate else RuleStatus.DRAFT

    created: list[BehavioralRule] = []
    for rule_def in template.get("rules", []):
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

    # Persist to rules JSON
    existing: list[dict[str, Any]] = []
    if rules_path.exists():
        raw = rules_path.read_text()
        if raw.strip():
            existing = json.loads(raw)

    for rule in created:
        existing.append(json.loads(rule.model_dump_json()))

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(existing, indent=2, default=str))

    return created
