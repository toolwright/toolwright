"""Groups command group for listing and inspecting tool groups."""
from __future__ import annotations

import json
from pathlib import Path

import click

from toolwright.utils.text import pluralize


def register_groups_commands(*, cli: click.Group) -> None:
    """Register the groups command group on the provided CLI group."""

    @cli.group()
    def groups() -> None:
        """List and inspect auto-generated tool groups."""

    @groups.command("list")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml",
    )
    @click.pass_context
    def groups_list(ctx: click.Context, toolpack: str | None) -> None:
        """List all tool groups with their tool counts.

        \b
        Examples:
          toolwright groups list
          toolwright groups list --toolpack toolpack.yaml
        """
        groups_path = _resolve_groups_path(toolpack, ctx)
        if groups_path is None or not groups_path.exists():
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        from toolwright.core.compile.grouper import load_groups_index

        index = load_groups_index(groups_path)
        if index is None or not index.groups:
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        total_tools = sum(len(g.tools) for g in index.groups) + len(index.ungrouped)
        click.echo(f"\nGroups ({len(index.groups)} groups, {pluralize(total_tools, 'tool')} total):\n")

        # Find max name length for alignment
        max_name = max(len(g.name) for g in index.groups)
        for group in index.groups:
            count_str = pluralize(len(group.tools), "tool")
            desc = group.description or ""
            click.echo(f"  {group.name:<{max_name + 2}} {count_str:>10}   {desc}")

        if index.ungrouped:
            click.echo(f"\n  Ungrouped: {pluralize(len(index.ungrouped), 'tool')}")

        click.echo("\nServe a subset: toolwright serve --scope <group1>,<group2>")

    @groups.command("show")
    @click.argument("name")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml",
    )
    @click.pass_context
    def groups_show(ctx: click.Context, name: str, toolpack: str | None) -> None:
        """Show tools in a specific group.

        \b
        Examples:
          toolwright groups show products
          toolwright groups show repos/issues --toolpack toolpack.yaml
        """
        groups_path = _resolve_groups_path(toolpack, ctx)
        if groups_path is None or not groups_path.exists():
            click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
            ctx.exit(1)
            return

        from toolwright.core.compile.grouper import load_groups_index, suggest_group_name

        index = load_groups_index(groups_path)
        if index is None:
            click.echo("No tool groups found.", err=True)
            ctx.exit(1)
            return

        # Find the group
        group = next((g for g in index.groups if g.name == name.lower()), None)
        if group is None:
            available = [g.name for g in index.groups]
            suggestion = suggest_group_name(name, available)
            msg = f"Error: Unknown group '{name}'."
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            msg += f"\nAvailable: {', '.join(sorted(available))}"
            click.echo(msg, err=True)
            ctx.exit(1)
            return

        # Load tools.json for method/path details
        tools_path = _resolve_tools_path(toolpack, ctx)
        action_details: dict[str, dict[str, str]] = {}
        if tools_path and tools_path.exists():
            with open(tools_path) as f:
                manifest = json.load(f)
            for action in manifest.get("actions", []):
                action_details[action["name"]] = {
                    "method": action.get("method", "GET"),
                    "path": action.get("path", "/"),
                }

        click.echo(f"\nGroup: {group.name} ({pluralize(len(group.tools), 'tool')})")
        click.echo(f"Path prefix: {group.path_prefix}\n")

        for tool_name in group.tools:
            detail = action_details.get(tool_name, {})
            method = detail.get("method", "")
            path = detail.get("path", "")
            click.echo(f"  {tool_name:<30} {method:<7} {path}")

        click.echo(f"\nServe this group: toolwright serve --scope {group.name}")


def _resolve_groups_path(toolpack: str | None, ctx: click.Context) -> Path | None:
    """Resolve groups.json path from toolpack or auto-discovery."""
    if toolpack:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(toolpack)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=toolpack)
        return resolved.groups_path

    # Auto-resolve toolpack
    try:
        from toolwright.utils.resolve import resolve_toolpack_path

        tp_path = resolve_toolpack_path(root=ctx.obj.get("root") if ctx.obj else None)
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=tp_path)
        return resolved.groups_path
    except (FileNotFoundError, click.UsageError):
        return None


def _resolve_tools_path(toolpack: str | None, ctx: click.Context) -> Path | None:
    """Resolve tools.json path from toolpack or auto-discovery."""
    if toolpack:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(toolpack)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=toolpack)
        return resolved.tools_path

    try:
        from toolwright.utils.resolve import resolve_toolpack_path

        tp_path = resolve_toolpack_path(root=ctx.obj.get("root") if ctx.obj else None)
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=tp_path)
        return resolved.tools_path
    except (FileNotFoundError, click.UsageError):
        return None
