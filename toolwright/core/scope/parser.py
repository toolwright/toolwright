"""YAML parser for custom scope definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from toolwright.models.scope import (
    FilterOperator,
    Scope,
    ScopeFilter,
    ScopeRule,
    ScopeType,
)


def parse_scope_file(path: str | Path) -> Scope:
    """Parse a scope YAML file.

    Args:
        path: Path to the scope YAML file

    Returns:
        Parsed Scope object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is invalid
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Scope file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return parse_scope_dict(data)


def parse_scope_dict(data: dict[str, Any]) -> Scope:
    """Parse a scope from a dictionary.

    Args:
        data: Scope definition as dict

    Returns:
        Parsed Scope object

    Raises:
        ValueError: If data is invalid
    """
    if not isinstance(data, dict):
        raise ValueError("Scope definition must be a dictionary")

    name = data.get("name")
    if not name:
        raise ValueError("Scope must have a 'name' field")

    # Parse type
    type_str = data.get("type", "custom")
    try:
        scope_type = ScopeType(type_str)
    except ValueError:
        scope_type = ScopeType.CUSTOM

    # Parse tag shorthand into rules
    rules = _expand_tag_shorthand(data.get("tags"))

    # Parse explicit rules
    for rule_data in data.get("rules", []):
        rules.append(_parse_rule(rule_data))

    return Scope(
        name=name,
        type=scope_type,
        description=data.get("description"),
        first_party_hosts=data.get("first_party_hosts", []),
        rules=rules,
        default_risk_tier=data.get("default_risk_tier", "medium"),
        confirmation_required=data.get("confirmation_required", False),
        rate_limit_per_minute=data.get("rate_limit_per_minute"),
    )


def _expand_tag_shorthand(tags_data: dict[str, Any] | None) -> list[ScopeRule]:
    """Expand tag shorthand syntax into ScopeRule objects.

    Supports:
        tags:
          include: [commerce, products]
          exclude: [auth, admin]

    Each tag becomes a separate ScopeRule with a single CONTAINS filter on
    the "tags" field. Include tags become include=True rules, exclude tags
    become include=False rules.
    """
    if not tags_data or not isinstance(tags_data, dict):
        return []

    rules: list[ScopeRule] = []

    for tag in tags_data.get("include", []):
        rules.append(
            ScopeRule(
                name=f"include_tag_{tag}",
                description=f"Include endpoints tagged '{tag}'",
                include=True,
                filters=[
                    ScopeFilter(
                        field="tags",
                        operator=FilterOperator.CONTAINS,
                        value=tag,
                    ),
                ],
            )
        )

    for tag in tags_data.get("exclude", []):
        rules.append(
            ScopeRule(
                name=f"exclude_tag_{tag}",
                description=f"Exclude endpoints tagged '{tag}'",
                include=False,
                filters=[
                    ScopeFilter(
                        field="tags",
                        operator=FilterOperator.CONTAINS,
                        value=tag,
                    ),
                ],
            )
        )

    return rules


def _parse_rule(data: dict[str, Any]) -> ScopeRule:
    """Parse a scope rule from a dictionary.

    Args:
        data: Rule definition as dict

    Returns:
        Parsed ScopeRule object
    """
    filters = []
    for filter_data in data.get("filters", []):
        filters.append(_parse_filter(filter_data))

    return ScopeRule(
        name=data.get("name"),
        description=data.get("description"),
        filters=filters,
        include=data.get("include", True),
    )


def _parse_filter(data: dict[str, Any]) -> ScopeFilter:
    """Parse a scope filter from a dictionary.

    Args:
        data: Filter definition as dict

    Returns:
        Parsed ScopeFilter object

    Raises:
        ValueError: If filter is invalid
    """
    field = data.get("field")
    if not field:
        raise ValueError("Filter must have a 'field'")

    operator_str = data.get("operator", "equals")
    try:
        operator = FilterOperator(operator_str)
    except ValueError as err:
        raise ValueError(f"Invalid operator: {operator_str}") from err

    value = data.get("value")
    if value is None:
        raise ValueError("Filter must have a 'value'")

    return ScopeFilter(
        field=field,
        operator=operator,
        value=value,
    )


def serialize_scope(scope: Scope) -> dict[str, Any]:
    """Serialize a scope to a dictionary for YAML output.

    Args:
        scope: Scope to serialize

    Returns:
        Dictionary suitable for YAML serialization
    """
    data: dict[str, Any] = {
        "name": scope.name,
        "description": scope.description,
    }

    if scope.type != ScopeType.CUSTOM:
        data["type"] = scope.type.value

    if scope.first_party_hosts:
        data["first_party_hosts"] = scope.first_party_hosts

    if scope.rules:
        data["rules"] = [_serialize_rule(rule) for rule in scope.rules]

    data["default_risk_tier"] = scope.default_risk_tier
    data["confirmation_required"] = scope.confirmation_required

    if scope.rate_limit_per_minute:
        data["rate_limit_per_minute"] = scope.rate_limit_per_minute

    return data


def _serialize_rule(rule: ScopeRule) -> dict[str, Any]:
    """Serialize a rule to a dictionary."""
    data: dict[str, Any] = {}

    if rule.name:
        data["name"] = rule.name
    if rule.description:
        data["description"] = rule.description

    data["include"] = rule.include

    if rule.filters:
        data["filters"] = [_serialize_filter(f) for f in rule.filters]

    return data


def _serialize_filter(filter_: ScopeFilter) -> dict[str, Any]:
    """Serialize a filter to a dictionary."""
    return {
        "field": filter_.field,
        "operator": filter_.operator.value,
        "value": filter_.value,
    }
