# Rule Templates + Recipe System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship rule templates (reusable behavioral rules) and API recipes (bundled configs for known APIs) as a single workstream.

**Architecture:** Three schema extensions to BehavioralRule/PrerequisiteConfig, a YAML template loader, a YAML recipe loader, a 10-line auth header name fix in server.py, and CLI commands for both. Templates and recipes are bundled YAML files in the package.

**Tech Stack:** Python 3.11+, Pydantic models, Click CLI, PyYAML (already a dependency), fnmatch (stdlib)

**Design doc:** `docs/plans/2026-03-01-rule-templates-and-recipes-design.md`

**Test command:** `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v`

**Lint command:** `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check`

---

## Task 1: Add `target_name_patterns` and `match` to BehavioralRule

**Files:**
- Modify: `toolwright/models/rule.py:113-126`
- Modify: `toolwright/core/correct/engine.py:115-131`
- Test: `tests/test_rule_name_patterns.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_rule_name_patterns.py
"""Tests for glob-based tool name pattern matching in rule targeting."""

from __future__ import annotations

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.models.rule import (
    BehavioralRule,
    ProhibitionConfig,
    RuleKind,
    RuleStatus,
)


def test_target_name_patterns_matches_glob(tmp_path):
    """A rule with target_name_patterns should match tool names via glob."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-1",
        kind=RuleKind.PROHIBITION,
        description="Block all delete tools",
        target_name_patterns=["delete_*", "*_delete"],
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Should match delete_product
    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Should match bulk_delete
    result = engine.evaluate("bulk_delete", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Should NOT match get_products
    result = engine.evaluate("get_products", "GET", "api.example.com", {}, session)
    assert result.allowed


def test_match_all_requires_both_fields(tmp_path):
    """match=all means tool must match ALL non-empty targeting fields."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-2",
        kind=RuleKind.PROHIBITION,
        description="Block delete_* AND DELETE method",
        target_name_patterns=["delete_*"],
        target_methods=["DELETE"],
        match="all",  # default
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Matches both pattern AND method -> blocked
    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Matches pattern but NOT method -> allowed (all = AND)
    result = engine.evaluate("delete_product", "GET", "api.example.com", {}, session)
    assert result.allowed

    # Matches method but NOT pattern -> allowed (all = AND)
    result = engine.evaluate("remove_product", "DELETE", "api.example.com", {}, session)
    assert result.allowed


def test_match_any_requires_either_field(tmp_path):
    """match=any means tool matches if ANY non-empty targeting field hits."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-3",
        kind=RuleKind.PROHIBITION,
        description="Block delete_* OR DELETE method",
        target_name_patterns=["delete_*"],
        target_methods=["DELETE"],
        match="any",
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Matches pattern (regardless of method) -> blocked
    result = engine.evaluate("delete_product", "GET", "api.example.com", {}, session)
    assert not result.allowed

    # Matches method (regardless of pattern) -> blocked
    result = engine.evaluate("remove_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Matches neither -> allowed
    result = engine.evaluate("get_products", "GET", "api.example.com", {}, session)
    assert result.allowed


def test_empty_patterns_match_all(tmp_path):
    """Empty target_name_patterns should not filter anything (backward compat)."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-4",
        kind=RuleKind.PROHIBITION,
        description="Block everything",
        # No targeting fields = matches all
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()
    result = engine.evaluate("any_tool", "GET", "api.example.com", {}, session)
    assert not result.allowed
```

**Step 2: Run test to verify it fails**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_name_patterns.py -v`

Expected: FAIL — `target_name_patterns` field not recognized by BehavioralRule

**Step 3: Add fields to BehavioralRule model**

In `toolwright/models/rule.py`, add to `BehavioralRule` class (after line 123):

```python
    target_name_patterns: list[str] = Field(default_factory=list)
    match: Literal["any", "all"] = "all"
```

Add `Literal` to imports at top of file:

```python
from typing import Any, Literal
```

**Step 4: Update `_applicable_rules()` in engine.py**

Replace lines 115-131 in `toolwright/core/correct/engine.py`:

```python
    def _applicable_rules(
        self, tool_id: str, method: str, host: str
    ) -> list[BehavioralRule]:
        """Filter rules by targets, skip disabled, sort by priority."""
        from fnmatch import fnmatch

        result = []
        for rule in self._rules.values():
            if rule.status != RuleStatus.ACTIVE:
                continue
            if not self._matches_targets(rule, tool_id, method, host):
                continue
            result.append(rule)
        result.sort(key=lambda r: r.priority)
        return result

    @staticmethod
    def _matches_targets(
        rule: BehavioralRule, tool_id: str, method: str, host: str
    ) -> bool:
        """Check if a tool call matches rule targeting fields.

        match="all": tool must match ALL non-empty targeting fields (AND).
        match="any": tool matches if ANY non-empty targeting field hits (OR).
        Empty fields are ignored.
        """
        from fnmatch import fnmatch

        checks: list[bool] = []

        if rule.target_tool_ids:
            checks.append(tool_id in rule.target_tool_ids)
        if rule.target_name_patterns:
            checks.append(
                any(fnmatch(tool_id, pat) for pat in rule.target_name_patterns)
            )
        if rule.target_methods:
            checks.append(method in rule.target_methods)
        if rule.target_hosts:
            checks.append(host in rule.target_hosts)

        if not checks:
            return True  # no targeting = matches all

        if rule.match == "any":
            return any(checks)
        return all(checks)
```

**Step 5: Run tests to verify they pass**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_name_patterns.py -v`

Expected: All 4 tests PASS

**Step 6: Run full test suite for regressions**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`

Expected: No new failures (2 pre-existing stdin failures in test_ui_wizard.py are OK)

**Step 7: Lint**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check toolwright/models/rule.py toolwright/core/correct/engine.py tests/test_rule_name_patterns.py`

Expected: All checks passed

**Step 8: Commit**

```bash
git add toolwright/models/rule.py toolwright/core/correct/engine.py tests/test_rule_name_patterns.py
git commit -m "feat(rules): add target_name_patterns and match field for glob-based rule targeting

Adds two fields to BehavioralRule:
- target_name_patterns: glob patterns matched via fnmatch
- match: 'all' (AND, default) or 'any' (OR)

Updates _applicable_rules() to support pattern matching alongside
existing exact-match fields. Backward compatible — empty patterns
match all, preserving existing behavior."
```

---

## Task 2: Add `required_tool_patterns` to PrerequisiteConfig

**Files:**
- Modify: `toolwright/models/rule.py:40-44`
- Modify: `toolwright/core/correct/engine.py:158-189`
- Test: `tests/test_rule_name_patterns.py` (append)

**Step 1: Write the failing test**

Append to `tests/test_rule_name_patterns.py`:

```python
from toolwright.models.rule import PrerequisiteConfig


def test_required_tool_patterns_matches_session_history(tmp_path):
    """Prerequisite with required_tool_patterns should check session via glob."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="prereq-1",
        kind=RuleKind.PREREQUISITE,
        description="Must read before delete",
        target_name_patterns=["delete_*"],
        match="any",
        config=PrerequisiteConfig(
            required_tool_ids=[],
            required_tool_patterns=["get_*", "list_*"],
        ),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # No prior calls -> violation
    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed
    assert "prerequisite" in result.violations[0].feedback.lower()

    # Call get_product -> satisfies pattern
    session.record("get_product", "GET", "api.example.com", {}, "200")

    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert result.allowed


def test_required_tool_patterns_empty_does_not_block(tmp_path):
    """Empty required_tool_patterns should not add any prerequisite checks."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="prereq-2",
        kind=RuleKind.PREREQUISITE,
        description="No patterns",
        config=PrerequisiteConfig(
            required_tool_ids=[],
            required_tool_patterns=[],
        ),
    )
    engine.add_rule(rule)

    session = SessionHistory()
    result = engine.evaluate("any_tool", "GET", "api.example.com", {}, session)
    assert result.allowed
```

**Step 2: Run test to verify it fails**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_name_patterns.py::test_required_tool_patterns_matches_session_history -v`

Expected: FAIL — `required_tool_patterns` not a valid field

**Step 3: Add field to PrerequisiteConfig**

In `toolwright/models/rule.py`, line 40-44, change:

```python
class PrerequisiteConfig(BaseModel):
    """Tool X must be called before tool Y."""

    required_tool_ids: list[str]
    required_args: dict[str, Any] = Field(default_factory=dict)
    required_tool_patterns: list[str] = Field(default_factory=list)
```

**Step 4: Update `_evaluate_prerequisite()` in engine.py**

Replace lines 158-189 in `toolwright/core/correct/engine.py`:

```python
    def _evaluate_prerequisite(
        self,
        rule: BehavioralRule,
        tool_id: str,
        _params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        from fnmatch import fnmatch

        config: PrerequisiteConfig = rule.config  # type: ignore[assignment]
        required_args = config.required_args or {}

        # Check exact tool ID prerequisites
        for req_tool in config.required_tool_ids:
            if required_args:
                if not session.has_called(req_tool, with_args=required_args):
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Prerequisite not met: {req_tool} with args {required_args}",
                        suggestion=f"Call {req_tool} with {required_args} first.",
                    )
            else:
                if not session.has_called(req_tool):
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Prerequisite not met: {req_tool} not called",
                        suggestion=f"Call {req_tool} first.",
                    )

        # Check glob pattern prerequisites
        for pattern in config.required_tool_patterns:
            called_ids = session.call_sequence()
            if not any(fnmatch(cid, pattern) for cid in called_ids):
                return RuleViolation(
                    rule_id=rule.rule_id,
                    rule_kind=rule.kind,
                    tool_id=tool_id,
                    description=rule.description,
                    feedback=f"Prerequisite not met: no tool matching '{pattern}' called",
                    suggestion=f"Call a tool matching '{pattern}' first (e.g., get_* or list_*).",
                )

        return None
```

**Step 5: Run tests to verify they pass**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_name_patterns.py -v`

Expected: All 6 tests PASS

**Step 6: Full suite + lint**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check toolwright/models/rule.py toolwright/core/correct/engine.py tests/test_rule_name_patterns.py`

**Step 7: Commit**

```bash
git add toolwright/models/rule.py toolwright/core/correct/engine.py tests/test_rule_name_patterns.py
git commit -m "feat(rules): add required_tool_patterns for glob-based prerequisites

PrerequisiteConfig now supports required_tool_patterns in addition to
required_tool_ids. Patterns are matched via fnmatch against session
history. Enables templates to express 'require get_* before delete_*'
without knowing specific tool names."
```

---

## Task 3: Rule template YAML loader + CLI

**Files:**
- Create: `toolwright/rules/templates/crud-safety.yaml`
- Create: `toolwright/rules/templates/rate-control.yaml`
- Create: `toolwright/rules/templates/retry-safety.yaml`
- Create: `toolwright/rules/__init__.py`
- Create: `toolwright/rules/loader.py`
- Modify: `toolwright/cli/commands_rules.py` (add template subcommands)
- Test: `tests/test_rule_templates.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_rule_templates.py
"""Tests for rule template loading and application."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.rules.loader import list_templates, load_template, apply_template


def test_list_templates_returns_bundled():
    """list_templates should return the 3 bundled templates."""
    templates = list_templates()
    names = {t["name"] for t in templates}
    assert "crud-safety" in names
    assert "rate-control" in names
    assert "retry-safety" in names


def test_load_template_returns_parsed_yaml():
    """load_template should return the full template dict."""
    template = load_template("crud-safety")
    assert template["name"] == "crud-safety"
    assert len(template["rules"]) == 3
    assert template["rules"][0]["kind"] == "prerequisite"


def test_load_template_unknown_raises():
    """load_template should raise ValueError for unknown template."""
    import pytest
    with pytest.raises(ValueError, match="Unknown rule template"):
        load_template("nonexistent")


def test_apply_template_creates_draft_rules(tmp_path):
    """apply_template should create DRAFT rules in the rules JSON file."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("retry-safety", rules_path=rules_path)
    assert len(created) == 1
    assert created[0].status.value == "draft"
    assert created[0].kind.value == "rate"

    # Verify persisted
    data = json.loads(rules_path.read_text())
    assert len(data) == 1
    assert data[0]["status"] == "draft"


def test_apply_template_with_activate(tmp_path):
    """apply_template with activate=True should create ACTIVE rules."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("retry-safety", rules_path=rules_path, activate=True)
    assert created[0].status.value == "active"
```

**Step 2: Run test to verify it fails**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_templates.py -v`

Expected: FAIL — `toolwright.rules.loader` does not exist

**Step 3: Create template YAML files**

Create `toolwright/rules/__init__.py` (empty).

Create `toolwright/rules/templates/crud-safety.yaml`:

```yaml
name: crud-safety
description: Require reading a resource before destructive operations
rules:
  - kind: prerequisite
    name: read-before-delete
    description: Require a read call before any destructive operation
    target_name_patterns: ["delete_*", "*_delete", "remove_*", "destroy_*"]
    target_methods: [DELETE]
    match: any
    config:
      required_tool_ids: []
      required_tool_patterns: ["get_*", "list_*", "read_*", "fetch_*"]
    priority: 100

  - kind: prerequisite
    name: read-before-update
    description: Require a read call before any mutation
    target_name_patterns: ["update_*", "*_update", "edit_*", "modify_*"]
    target_methods: [PUT, PATCH]
    match: any
    config:
      required_tool_ids: []
      required_tool_patterns: ["get_*", "list_*", "read_*", "fetch_*"]
    priority: 100

  - kind: approval
    name: confirm-destructive
    description: Require confirmation before destructive operations
    target_name_patterns: ["delete_*", "*_delete", "remove_*", "destroy_*"]
    target_methods: [DELETE]
    match: any
    config:
      approval_message: "This will permanently delete a resource. Confirm?"
    priority: 50
```

Create `toolwright/rules/templates/rate-control.yaml`:

```yaml
name: rate-control
description: Rate limits on write operations and session budgets
rules:
  - kind: rate
    name: write-rate-limit
    description: Limit write operations to 10 per minute
    target_name_patterns: ["create_*", "update_*", "delete_*", "post_*", "put_*"]
    target_methods: [POST, PUT, PATCH, DELETE]
    match: any
    config:
      max_calls: 10
      window_seconds: 60
      per_tool: false
    priority: 100

  - kind: rate
    name: session-budget
    description: Cap total tool calls at 200 per session
    # window_seconds null = entire session (no time window)
    config:
      max_calls: 200
      window_seconds: null
      per_tool: false
    priority: 200
```

Create `toolwright/rules/templates/retry-safety.yaml`:

```yaml
name: retry-safety
description: Prevent agents from retrying failed calls unproductively
rules:
  - kind: rate
    name: limit-consecutive-errors
    description: Rate limit any single tool to 3 calls per 30 seconds
    config:
      max_calls: 3
      window_seconds: 30
      per_tool: true
    priority: 100
```

**Step 4: Create `toolwright/rules/loader.py`**

```python
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
        available = [p.stem for p in _TEMPLATES_DIR.glob("*.yaml")]
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

    Returns the list of created BehavioralRule objects.
    """
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
```

**Step 5: Run tests to verify they pass**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_rule_templates.py -v`

Expected: All 5 tests PASS

**Step 6: Add CLI subcommands to commands_rules.py**

In `toolwright/cli/commands_rules.py`, add inside `register_rules_commands()`, after the existing subcommands:

```python
    @rules.group("template")
    def rules_template():
        """Manage rule templates."""
        pass

    @rules_template.command("list")
    def template_list():
        """List available rule templates."""
        from toolwright.rules.loader import list_templates

        templates = list_templates()
        if not templates:
            click.echo("No rule templates found.")
            return
        for t in templates:
            click.echo(f"  {t['name']:<20} {t['description']} ({t['rule_count']} rules)")

    @rules_template.command("show")
    @click.argument("name")
    def template_show(name: str):
        """Show details of a rule template."""
        from toolwright.rules.loader import load_template

        try:
            template = load_template(name)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Template: {template['name']}")
        click.echo(f"Description: {template.get('description', '')}")
        click.echo(f"Rules ({len(template.get('rules', []))}):")
        for r in template.get("rules", []):
            click.echo(f"  - [{r['kind']}] {r['name']}: {r['description']}")

    @rules_template.command("apply")
    @click.argument("name")
    @click.option("--activate", is_flag=True, help="Create rules as ACTIVE instead of DRAFT.")
    @click.pass_context
    def template_apply(ctx: click.Context, name: str, activate: bool):
        """Apply a rule template to the active toolpack."""
        from toolwright.rules.loader import apply_template

        rules_path = ctx.obj["rules_path"]
        try:
            created = apply_template(name, rules_path=rules_path, activate=activate)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        status = "ACTIVE" if activate else "DRAFT"
        click.echo(f"Applied template '{name}': {len(created)} rules created as {status}.")
        for r in created:
            click.echo(f"  {r.rule_id}: {r.description}")
        if not activate:
            click.echo(f"\nActivate with: toolwright rules activate <rule-id>")
```

**Step 7: Full suite + lint + commit**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check toolwright/rules/ toolwright/cli/commands_rules.py tests/test_rule_templates.py`

```bash
git add toolwright/rules/ tests/test_rule_templates.py toolwright/cli/commands_rules.py
git commit -m "feat(rules): add bundled rule templates with loader and CLI

Three templates: crud-safety, rate-control, retry-safety.
YAML loader reads from toolwright/rules/templates/*.yaml.
CLI: toolwright rules template list|show|apply.
Applied rules are created as DRAFT by default."
```

---

## Task 4: Wire per-host auth header name at runtime

**Files:**
- Modify: `toolwright/mcp/server.py:520-524,690-695`
- Test: `tests/test_auth_header_name.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_auth_header_name.py
"""Tests for per-host auth header name resolution."""

from __future__ import annotations

from toolwright.core.toolpack import ToolpackAuthRequirement


def test_auth_requirement_stores_header_name():
    """ToolpackAuthRequirement should store custom header names."""
    req = ToolpackAuthRequirement(
        host="shop.myshopify.com",
        scheme="api_key",
        location="header",
        header_name="X-Shopify-Access-Token",
        env_var_name="TOOLWRIGHT_AUTH_SHOP_MYSHOPIFY_COM",
    )
    assert req.header_name == "X-Shopify-Access-Token"


def test_auth_requirement_defaults_to_none():
    """header_name should default to None."""
    req = ToolpackAuthRequirement(
        host="api.github.com",
        scheme="bearer",
        location="header",
        env_var_name="TOOLWRIGHT_AUTH_API_GITHUB_COM",
    )
    assert req.header_name is None
```

Note: The full runtime test for header injection requires a running server. The implementation is a 2-line change at each injection site. Verify manually or with an integration test that the header name is respected. The key unit test is that the model stores and returns the header_name field correctly (which it already does — this test codifies the existing behavior before we wire it).

**Step 2: Run test**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_auth_header_name.py -v`

Expected: PASS (the model already has this field — this test locks in the contract)

**Step 3: Create `_resolve_auth_header_name` helper in server.py**

Find `_resolve_auth_for_host` in `toolwright/mcp/server.py` and add after it:

```python
    def _resolve_auth_header_name(self, host: str) -> str:
        """Resolve which header name to use for auth on this host.

        Checks ToolpackAuthRequirement entries for a custom header_name.
        Falls back to 'Authorization'.
        """
        if hasattr(self, "_auth_requirements") and self._auth_requirements:
            for req in self._auth_requirements:
                if req.host == host and req.header_name:
                    return req.header_name
        return "Authorization"
```

**Step 4: Replace hardcoded `headers["Authorization"]` at both injection sites**

Line ~522:
```python
# Before:
headers["Authorization"] = auth
# After:
headers[self._resolve_auth_header_name(action_host)] = auth
```

Line ~693:
```python
# Before:
headers["Authorization"] = auth
# After:
headers[self._resolve_auth_header_name(action_host)] = auth
```

**Step 5: Verify `_auth_requirements` is populated from toolpack**

Search for where `auth_requirements` from the toolpack are loaded into the server instance. If not wired, add it to the `ToolwrightServer.__init__()` method where the toolpack is loaded. The server needs access to `resolved_toolpack.auth_requirements` to look up header names.

**Step 6: Full suite + lint + commit**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check toolwright/mcp/server.py tests/test_auth_header_name.py`

```bash
git add toolwright/mcp/server.py tests/test_auth_header_name.py
git commit -m "feat(auth): wire per-host auth header name at runtime

ToolpackAuthRequirement.header_name was already stored but ignored.
Now _resolve_auth_header_name() reads it at both injection sites.
Enables APIs like Shopify (X-Shopify-Access-Token) to work without
workarounds. Falls back to Authorization when no custom name set."
```

---

## Task 5: Recipe YAML format, loader, and CLI

**Files:**
- Create: `toolwright/recipes/__init__.py`
- Create: `toolwright/recipes/loader.py`
- Create: `toolwright/recipes/github.yaml`
- Create: `toolwright/recipes/shopify.yaml`
- Create: `toolwright/recipes/notion.yaml`
- Create: `toolwright/recipes/stripe.yaml`
- Create: `toolwright/recipes/slack.yaml`
- Create: `toolwright/cli/commands_recipes.py`
- Modify: `toolwright/cli/main.py` (register recipes commands)
- Test: `tests/test_recipes.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_recipes.py
"""Tests for recipe loading and validation."""

from __future__ import annotations

from toolwright.recipes.loader import list_recipes, load_recipe


def test_list_recipes_returns_bundled():
    """list_recipes should return at least 5 bundled recipes."""
    recipes = list_recipes()
    names = {r["name"] for r in recipes}
    assert "github" in names
    assert "shopify" in names
    assert "notion" in names
    assert "stripe" in names
    assert "slack" in names


def test_load_recipe_returns_parsed_yaml():
    """load_recipe should return a full recipe dict."""
    recipe = load_recipe("github")
    assert recipe["name"] == "github"
    assert "hosts" in recipe
    assert len(recipe["hosts"]) >= 1
    assert "rule_templates" in recipe


def test_load_recipe_unknown_raises():
    """load_recipe should raise ValueError for unknown recipe."""
    import pytest
    with pytest.raises(ValueError, match="Unknown recipe"):
        load_recipe("nonexistent")


def test_shopify_recipe_has_custom_auth_header():
    """Shopify recipe should specify X-Shopify-Access-Token."""
    recipe = load_recipe("shopify")
    host = recipe["hosts"][0]
    assert host["auth_header_name"] == "X-Shopify-Access-Token"


def test_notion_recipe_has_extra_headers():
    """Notion recipe should specify Notion-Version header."""
    recipe = load_recipe("notion")
    assert "Notion-Version" in recipe.get("extra_headers", {})
```

**Step 2: Run test to verify it fails**

Expected: FAIL — `toolwright.recipes.loader` does not exist

**Step 3: Create recipe YAML files and loader**

Create `toolwright/recipes/__init__.py` (empty).

Create `toolwright/recipes/loader.py`:

```python
"""Load bundled API recipes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_RECIPES_DIR = Path(__file__).parent


def list_recipes() -> list[dict[str, Any]]:
    """Return metadata for all bundled recipes."""
    results = []
    for path in sorted(_RECIPES_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        results.append({
            "name": data["name"],
            "description": data.get("description", ""),
            "hosts": [h.get("pattern", "") for h in data.get("hosts", [])],
        })
    return results


def load_recipe(name: str) -> dict[str, Any]:
    """Load a recipe by name. Raises ValueError if not found."""
    path = _RECIPES_DIR / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in _RECIPES_DIR.glob("*.yaml")]
        raise ValueError(
            f"Unknown recipe: {name}. "
            f"Available: {', '.join(available)}"
        )
    with open(path) as f:
        return yaml.safe_load(f)
```

Create recipe YAML files (5 files — `github.yaml`, `shopify.yaml`, `notion.yaml`, `stripe.yaml`, `slack.yaml`). Each follows the format in the design doc. Example for `shopify.yaml`:

```yaml
name: shopify
description: Shopify Admin REST API
hosts:
  - pattern: "*.myshopify.com"
    auth_header_name: X-Shopify-Access-Token
    auth_scheme: api_key
extra_headers:
  Content-Type: application/json
setup_instructions_url: https://shopify.dev/docs/api/admin-rest
openapi_spec_url: null
rate_limit_hints: "2 req/sec at standard tier"
usage_notes: "All endpoints under /admin/api/{version}/."
rule_templates:
  - crud-safety
  - rate-control
probe_hints:
  expect_auth: true
  expect_openapi: false
```

Write all 5 recipe files with correct values per the design doc table.

**Step 4: Create CLI commands**

Create `toolwright/cli/commands_recipes.py`:

```python
"""Recipes command group for API configuration templates."""

from __future__ import annotations

import click


def register_recipes_commands(*, cli: click.Group) -> None:
    """Register the recipes command group."""

    @cli.group()
    def recipes():
        """Browse and use bundled API recipes."""
        pass

    @recipes.command("list")
    def recipes_list():
        """List available API recipes."""
        from toolwright.recipes.loader import list_recipes

        for r in list_recipes():
            hosts = ", ".join(r["hosts"])
            click.echo(f"  {r['name']:<15} {r['description']:<40} [{hosts}]")

    @recipes.command("show")
    @click.argument("name")
    def recipes_show(name: str):
        """Show details of an API recipe."""
        from toolwright.recipes.loader import load_recipe

        try:
            recipe = load_recipe(name)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Recipe: {recipe['name']}")
        click.echo(f"Description: {recipe.get('description', '')}")
        click.echo(f"\nHosts:")
        for h in recipe.get("hosts", []):
            header = h.get("auth_header_name", "Authorization")
            click.echo(f"  {h['pattern']} (auth via {header})")
        if recipe.get("extra_headers"):
            click.echo(f"\nExtra headers:")
            for k, v in recipe["extra_headers"].items():
                click.echo(f"  {k}: {v}")
        if recipe.get("rule_templates"):
            click.echo(f"\nRule templates: {', '.join(recipe['rule_templates'])}")
        if recipe.get("setup_instructions_url"):
            click.echo(f"\nSetup: {recipe['setup_instructions_url']}")
        if recipe.get("usage_notes"):
            click.echo(f"\nNotes: {recipe['usage_notes']}")
```

Register in `toolwright/cli/main.py` — find where other commands are registered and add:

```python
from toolwright.cli.commands_recipes import register_recipes_commands
register_recipes_commands(cli=cli)
```

**Step 5: Run tests + lint + commit**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_recipes.py -v`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check toolwright/recipes/ toolwright/cli/commands_recipes.py tests/test_recipes.py`

```bash
git add toolwright/recipes/ toolwright/cli/commands_recipes.py toolwright/cli/main.py tests/test_recipes.py
git commit -m "feat(recipes): add bundled API recipes with loader and CLI

Five recipes: github, shopify, notion, stripe, slack.
Each recipe defines hosts, auth header names, extra headers,
rule template references, and probe hints.
CLI: toolwright recipes list|show."
```

---

## Task 6: Wire `--recipe` into `mint` command

**Files:**
- Modify: `toolwright/cli/mint.py` (add `--recipe` option, apply recipe config)
- Modify: `toolwright/cli/main.py` (pass recipe through to run_mint)
- Test: `tests/test_mint_recipe.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_mint_recipe.py
"""Tests for mint --recipe integration."""

from __future__ import annotations

from toolwright.recipes.loader import load_recipe


def test_recipe_provides_allowed_hosts():
    """Recipe hosts should be usable as allowed_hosts for mint."""
    recipe = load_recipe("shopify")
    hosts = [h["pattern"] for h in recipe["hosts"]]
    assert len(hosts) >= 1
    assert "*.myshopify.com" in hosts


def test_recipe_provides_extra_headers():
    """Recipe extra_headers should be mergeable into mint headers."""
    recipe = load_recipe("notion")
    extra = recipe.get("extra_headers", {})
    assert "Notion-Version" in extra


def test_recipe_provides_rule_template_refs():
    """Recipe rule_templates should reference valid templates."""
    from toolwright.rules.loader import load_template

    recipe = load_recipe("shopify")
    for tmpl_name in recipe.get("rule_templates", []):
        # Should not raise
        template = load_template(tmpl_name)
        assert template["name"] == tmpl_name
```

**Step 2: Add `--recipe` option to mint CLI**

In `toolwright/cli/main.py`, find the `@cli.command("mint")` definition and add:

```python
@click.option("--recipe", "-r", default=None, help="Use a bundled API recipe (e.g., shopify, github).")
```

In `run_mint()` in `toolwright/cli/mint.py`, add `recipe: str | None = None` parameter. At the top of the function, before the probe step:

```python
    # Apply recipe if provided
    recipe_data = None
    if recipe:
        from toolwright.recipes.loader import load_recipe
        recipe_data = load_recipe(recipe)

        # Merge recipe hosts into allowed_hosts
        if not allowed_hosts:
            allowed_hosts = [h["pattern"] for h in recipe_data.get("hosts", [])]

        # Merge extra headers
        recipe_headers = recipe_data.get("extra_headers", {})
        if recipe_headers:
            if extra_headers is None:
                extra_headers = {}
            for k, v in recipe_headers.items():
                extra_headers.setdefault(k, v)

        click.echo(f"Using recipe: {recipe_data['name']}", err=True)
```

After compile/package step (post-mint), apply rule templates:

```python
    # Post-mint: apply recipe rule templates as DRAFT
    if recipe_data and recipe_data.get("rule_templates"):
        from toolwright.rules.loader import apply_template
        rules_path = Path(output_root) / ".toolwright" / "rules.json"
        for tmpl_name in recipe_data["rule_templates"]:
            try:
                created = apply_template(tmpl_name, rules_path=rules_path)
                click.echo(
                    f"  Applied rule template '{tmpl_name}': {len(created)} DRAFT rules",
                    err=True,
                )
            except ValueError:
                pass  # Unknown template — skip silently
```

**Step 3: Run tests + lint + commit**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/test_mint_recipe.py -v`
Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v 2>&1 | tail -5`

```bash
git add toolwright/cli/mint.py toolwright/cli/main.py tests/test_mint_recipe.py
git commit -m "feat(mint): add --recipe flag to pre-fill config from bundled recipes

mint --recipe shopify sets allowed_hosts, extra_headers, and auth
header names from the recipe. Post-mint, referenced rule templates
are created as DRAFT rules. Still requires browsing, review, and
approval — recipe reduces setup friction, not governance decisions."
```

---

## Task 7: Update docs and CAPABILITIES.md

**Files:**
- Modify: `CAPABILITIES.md` (add CAP-CORRECT-010, CAP-UX-008)
- Modify: `docs/quickstarts/github.md` (mention `--recipe github`)
- Modify: `docs/quickstarts/any-rest-api.md` (mention recipes)
- Modify: `docs/user-guide.md` (add rule templates and recipes sections)
- Modify: `README.md` (mention recipes in commands section)

**Step 1: Add capabilities**

Add to CAPABILITIES.md:

```markdown
### CAP-CORRECT-010: Rule Templates

Bundled reusable rule templates (crud-safety, rate-control, retry-safety) that create DRAFT behavioral rules. Templates use glob-based targeting (target_name_patterns) for overlay-forward compatibility.

- `toolwright/rules/templates/*.yaml` -> Template definitions
- `toolwright/rules/loader.py` -> `list_templates()`, `load_template()`, `apply_template()`
- `toolwright/cli/commands_rules.py` -> `rules template list|show|apply`
- CLI: `toolwright rules template list`, `toolwright rules template apply crud-safety`

### CAP-UX-008: API Recipes

Bundled YAML configs for known APIs (GitHub, Shopify, Notion, Stripe, Slack). Pre-configure auth headers, extra headers, rule template references, and probe hints. Used via `mint --recipe <name>`.

- `toolwright/recipes/*.yaml` -> Recipe definitions
- `toolwright/recipes/loader.py` -> `list_recipes()`, `load_recipe()`
- `toolwright/cli/commands_recipes.py` -> `recipes list|show`
- `toolwright/cli/mint.py` -> `--recipe` flag integration
- CLI: `toolwright recipes list`, `toolwright mint --recipe shopify`
```

**Step 2: Update quickstarts**

In `docs/quickstarts/github.md`, add a note after Step 3:

```markdown
> **Shortcut:** `toolwright mint --recipe github` pre-fills the API host and configures auth headers automatically.
```

In `docs/quickstarts/any-rest-api.md`, add to the Tips section:

```markdown
**Check for a recipe first.** Toolwright ships with built-in recipes for popular APIs:
\`\`\`bash
toolwright recipes list
toolwright mint --recipe shopify   # pre-fills hosts, auth, headers
\`\`\`
```

**Step 3: Update README commands section**

Add to the "Getting started" section:

```markdown
toolwright recipes list                 # see bundled API recipes
toolwright mint --recipe shopify        # pre-filled mint from recipe
toolwright rules template apply crud-safety  # apply behavioral rules
```

**Step 4: Commit**

```bash
git add CAPABILITIES.md docs/ README.md
git commit -m "docs: add rule templates and recipes to capabilities, quickstarts, and README"
```

---

## Task 8: Final verification

**Step 1: Full test suite**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m pytest tests/ -v`

Expected: All new tests pass, no regressions

**Step 2: Lint entire project**

Run: `/Users/thomasallicino/oss/toolwright/.venv/bin/python -m ruff check`

**Step 3: Manual verification**

Run these commands and verify output makes sense:

```bash
/Users/thomasallicino/oss/toolwright/.venv/bin/python -m toolwright recipes list
/Users/thomasallicino/oss/toolwright/.venv/bin/python -m toolwright recipes show shopify
/Users/thomasallicino/oss/toolwright/.venv/bin/python -m toolwright rules template list
/Users/thomasallicino/oss/toolwright/.venv/bin/python -m toolwright rules template show crud-safety
```

**Step 4: Verify YAML templates load correctly**

```bash
/Users/thomasallicino/oss/toolwright/.venv/bin/python -c "
from toolwright.rules.loader import list_templates, load_template
for t in list_templates():
    print(f'{t[\"name\"]}: {t[\"rule_count\"]} rules')
    tmpl = load_template(t['name'])
    for r in tmpl['rules']:
        print(f'  [{r[\"kind\"]}] {r[\"name\"]}')
"
```
