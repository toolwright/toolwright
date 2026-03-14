"""Recipes command group for API configuration templates."""

from __future__ import annotations

import click


def register_recipes_commands(*, cli: click.Group) -> None:
    """Register the recipes command group."""

    @cli.group(invoke_without_command=True)
    @click.pass_context
    def recipes(ctx: click.Context) -> None:
        """Browse and use bundled API recipes."""
        if ctx.invoked_subcommand is None:
            from toolwright.recipes.loader import list_recipes

            for r in list_recipes():
                hosts = ", ".join(r["hosts"])
                click.echo(f"  {r['name']:<15} {r['description']:<40} [{hosts}]")

    @recipes.command("list")
    def recipes_list() -> None:
        """List available API recipes."""
        from toolwright.recipes.loader import list_recipes

        for r in list_recipes():
            hosts = ", ".join(r["hosts"])
            click.echo(f"  {r['name']:<15} {r['description']:<40} [{hosts}]")

    @recipes.command("show")
    @click.argument("name")
    def recipes_show(name: str) -> None:
        """Show details of an API recipe."""
        from toolwright.recipes.loader import load_recipe

        try:
            recipe = load_recipe(name)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e

        click.echo(f"Recipe: {recipe['name']}")
        click.echo(f"Description: {recipe.get('description', '')}")
        click.echo("\nHosts:")
        for h in recipe.get("hosts", []):
            header = h.get("auth_header_name", "Authorization")
            click.echo(f"  {h['pattern']} (auth via {header})")
        if recipe.get("extra_headers"):
            click.echo("\nExtra headers:")
            for k, v in recipe["extra_headers"].items():
                click.echo(f"  {k}: {v}")
        if recipe.get("rule_templates"):
            click.echo(f"\nRule templates: {', '.join(recipe['rule_templates'])}")
        if recipe.get("setup_instructions_url"):
            click.echo(f"\nSetup: {recipe['setup_instructions_url']}")
        if recipe.get("usage_notes"):
            click.echo(f"\nNotes: {recipe['usage_notes']}")
