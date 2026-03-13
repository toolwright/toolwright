"""Rules command group for the CORRECT pillar.

CLI commands for managing behavioral rules: add, list, remove, show,
export, import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import click

from toolwright.core.correct.engine import RuleEngine
from toolwright.models.rule import (
    ApprovalConfig,
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleConfig,
    RuleKind,
    RuleStatus,
    SequenceConfig,
    SessionRateConfig,
)


def _default_rules_path() -> str:
    """Auto-discover rules from toolpack directory, falling back to global."""
    root = Path(".toolwright")
    # Check for rules.json inside any toolpack directory
    toolpack_rules = sorted(root.glob("toolpacks/*/rules.json"))
    if toolpack_rules:
        return str(toolpack_rules[0])
    return str(root / "rules.json")


def register_rules_commands(*, cli: click.Group) -> None:
    """Register the rules command group on the provided CLI group."""

    @cli.group()
    @click.option(
        "--rules-path",
        type=click.Path(),
        default=_default_rules_path(),
        show_default=True,
        help="Path to the behavioral rules JSON file.",
    )
    @click.pass_context
    def rules(ctx: click.Context, rules_path: str) -> None:
        """Manage behavioral rules for tool usage constraints."""
        ctx.ensure_object(dict)
        ctx.obj["rules_path"] = Path(rules_path)

    @rules.command("add")
    @click.option("--kind", "-k", required=True, type=click.Choice([k.value for k in RuleKind]), help="Rule kind.")
    @click.option("--target", "-t", multiple=True, help="Target tool IDs (repeatable).")
    @click.option("--description", "-d", required=True, help="Rule description.")
    @click.option("--requires", multiple=True, help="Required tool IDs (for prerequisite rules).")
    @click.option("--max-calls", type=int, help="Maximum call count (for rate rules).")
    @click.option("--param-name", help="Parameter name (for parameter rules).")
    @click.option("--allowed-values", help="Comma-separated allowed values (for parameter rules).")
    @click.option("--blocked-values", help="Comma-separated blocked values (for parameter rules).")
    @click.option("--pattern", help="Regex pattern for parameter validation (for parameter rules).")
    @click.option("--rule-id", help="Custom rule ID (auto-generated if omitted).")
    @click.pass_context
    def rules_add(
        ctx: click.Context,
        kind: str,
        target: tuple[str, ...],
        description: str,
        requires: tuple[str, ...],
        max_calls: int | None,
        param_name: str | None,
        allowed_values: str | None,
        blocked_values: str | None,
        pattern: str | None,
        rule_id: str | None,
    ) -> None:
        """Add a new behavioral rule."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)

        rid = rule_id or f"rule_{uuid4().hex[:8]}"
        rule_kind = RuleKind(kind)
        config = _build_config(
            rule_kind,
            requires=list(requires),
            max_calls=max_calls,
            param_name=param_name,
            allowed_values=allowed_values,
            blocked_values=blocked_values,
            pattern=pattern,
        )

        rule = BehavioralRule(
            rule_id=rid,
            kind=rule_kind,
            description=description,
            target_tool_ids=list(target),
            config=config,
        )
        engine.add_rule(rule)
        click.echo(f"Rule '{rid}' added ({kind}).")

    @rules.command("list")
    @click.option("--kind", "-k", type=click.Choice([k.value for k in RuleKind]), help="Filter by rule kind.")
    @click.pass_context
    def rules_list(ctx: click.Context, kind: str | None) -> None:
        """List all behavioral rules."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        all_rules = engine.list_rules()

        if kind:
            all_rules = [r for r in all_rules if r.kind.value == kind]

        if not all_rules:
            click.echo("No rules configured.")
            return

        for r in all_rules:
            targets = ", ".join(r.target_tool_ids) if r.target_tool_ids else "*"
            status = r.status.value
            click.echo(f"  {r.rule_id}  [{r.kind}]  {r.description}  targets={targets}  ({status})")

    @rules.command("show")
    @click.argument("rule_id")
    @click.pass_context
    def rules_show(ctx: click.Context, rule_id: str) -> None:
        """Show details of a specific rule."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        rule = engine.get_rule(rule_id)
        if rule is None:
            click.echo(f"Rule '{rule_id}' not found.", err=True)
            raise SystemExit(1)

        click.echo(json.dumps(rule.model_dump(mode="json"), indent=2, default=str))

    @rules.command("remove")
    @click.argument("rule_id")
    @click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
    @click.pass_context
    def rules_remove(ctx: click.Context, rule_id: str, yes: bool) -> None:
        """Remove a behavioral rule by ID."""
        if not yes:
            click.confirm(f"Remove rule '{rule_id}'?", default=False, abort=True)

        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        try:
            engine.remove_rule(rule_id)
            click.echo(f"Rule '{rule_id}' removed.")
        except KeyError as err:
            click.echo(f"Rule '{rule_id}' not found.", err=True)
            raise SystemExit(1) from err

    @rules.command("export")
    @click.option("--output", "-o", required=True, type=click.Path(), help="Output file path.")
    @click.pass_context
    def rules_export(ctx: click.Context, output: str) -> None:
        """Export all rules to a JSON file."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        all_rules = engine.list_rules()

        data = [r.model_dump(mode="json") for r in all_rules]
        Path(output).write_text(json.dumps(data, indent=2, default=str))
        click.echo(f"Exported {len(data)} rule(s) to {output}.")

    @rules.command("import")
    @click.option("--input", "-i", "input_path", required=True, type=click.Path(exists=True), help="Input file path.")
    @click.pass_context
    def rules_import(ctx: click.Context, input_path: str) -> None:
        """Import rules from a JSON file."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)

        data = json.loads(Path(input_path).read_text())
        imported = 0
        for item in data:
            rule = BehavioralRule.model_validate(item)
            if engine.get_rule(rule.rule_id) is None:
                engine.add_rule(rule)
                imported += 1

        click.echo(f"Imported {imported} rule(s).")

    @rules.command("drafts")
    @click.pass_context
    def rules_drafts(ctx: click.Context) -> None:
        """List behavioral rules in DRAFT status."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        drafts = [r for r in engine.list_rules() if r.status == RuleStatus.DRAFT]
        if not drafts:
            click.echo("No draft rules.")
            return
        for r in drafts:
            targets = ", ".join(r.target_tool_ids) if r.target_tool_ids else "*"
            click.echo(f"  {r.rule_id}  [{r.kind}]  {r.description}  targets={targets}")

    @rules.command("activate")
    @click.argument("rule_id")
    @click.pass_context
    def rules_activate(ctx: click.Context, rule_id: str) -> None:
        """Activate a DRAFT or DISABLED rule."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        rule = engine.get_rule(rule_id)
        if rule is None:
            click.echo(f"Rule not found: {rule_id}", err=True)
            raise SystemExit(1)
        if rule.status == RuleStatus.ACTIVE:
            click.echo(f"Rule {rule_id} is already active.")
            return
        engine.update_rule(rule_id, status=RuleStatus.ACTIVE)
        click.echo(f"Activated rule: {rule_id}")

    @rules.command("disable")
    @click.argument("rule_id")
    @click.pass_context
    def rules_disable(ctx: click.Context, rule_id: str) -> None:
        """Disable an ACTIVE rule."""
        rules_path = ctx.obj["rules_path"]
        engine = RuleEngine(rules_path=rules_path)
        rule = engine.get_rule(rule_id)
        if rule is None:
            click.echo(f"Rule not found: {rule_id}", err=True)
            raise SystemExit(1)
        if rule.status == RuleStatus.DISABLED:
            click.echo(f"Rule {rule_id} is already disabled.")
            return
        engine.update_rule(rule_id, status=RuleStatus.DISABLED)
        click.echo(f"Disabled rule: {rule_id}")

    # -----------------------------------------------------------------------
    # Template subgroup
    # -----------------------------------------------------------------------

    @rules.group("template")
    @click.pass_context
    def rules_template(ctx: click.Context) -> None:
        """Manage rule templates."""
        ctx.ensure_object(dict)

    @rules_template.command("list")
    def template_list() -> None:
        """List available rule templates."""
        from toolwright.rules.loader import list_templates

        templates = list_templates()
        if not templates:
            click.echo("No rule templates found.")
            return
        for t in templates:
            click.echo(
                f"  {t['name']:<20} {t['description']} ({t['rule_count']} rules)"
            )

    @rules_template.command("show")
    @click.argument("name")
    def template_show(name: str) -> None:
        """Show details of a rule template."""
        from toolwright.rules.loader import load_template

        try:
            template = load_template(name)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
        click.echo(f"Template: {template['name']}")
        click.echo(f"Description: {template.get('description', '')}")
        click.echo(f"Rules ({len(template.get('rules', []))}):")
        for r in template.get("rules", []):
            click.echo(f"  - [{r['kind']}] {r['name']}: {r['description']}")

    @rules_template.command("apply")
    @click.argument("name")
    @click.option(
        "--activate",
        is_flag=True,
        help="Create rules as ACTIVE instead of DRAFT.",
    )
    @click.pass_context
    def template_apply(ctx: click.Context, name: str, activate: bool) -> None:
        """Apply a rule template to the active toolpack."""
        from toolwright.rules.loader import apply_template

        rules_path = ctx.obj["rules_path"]
        try:
            created = apply_template(
                name, rules_path=rules_path, activate=activate
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
        status = "ACTIVE" if activate else "DRAFT"
        click.echo(
            f"Applied template '{name}': {len(created)} rules created as {status}."
        )
        for r in created:
            click.echo(f"  {r.rule_id}: {r.description}")
        if not activate:
            click.echo("\nActivate with: toolwright rules activate <rule-id>")


def _build_config(
    kind: RuleKind,
    *,
    requires: list[str],
    max_calls: int | None,
    param_name: str | None,
    allowed_values: str | None,
    blocked_values: str | None,
    pattern: str | None,
) -> RuleConfig:
    """Build the config model based on rule kind and CLI options."""
    if kind == RuleKind.PREREQUISITE:
        return PrerequisiteConfig(required_tool_ids=requires or [])
    if kind == RuleKind.PROHIBITION:
        return ProhibitionConfig(always=True)
    if kind == RuleKind.PARAMETER:
        config: dict[str, Any] = {"param_name": param_name or ""}
        if allowed_values:
            config["allowed_values"] = [v.strip() for v in allowed_values.split(",")]
        if blocked_values:
            config["blocked_values"] = [v.strip() for v in blocked_values.split(",")]
        if pattern:
            config["pattern"] = pattern
        return ParameterConfig(**config)
    if kind == RuleKind.RATE:
        return SessionRateConfig(max_calls=max_calls or 10, per_tool=True)
    if kind == RuleKind.SEQUENCE:
        return SequenceConfig(required_order=requires or [])
    if kind == RuleKind.APPROVAL:
        return ApprovalConfig(approval_message="Approval required.")
    raise ValueError(f"Unsupported rule kind: {kind}")
