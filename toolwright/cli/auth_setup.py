"""Interactive auth setup wizard."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Any

import click

from toolwright.cli.commands_auth import _probe_host
from toolwright.utils.auth import host_to_env_var
from toolwright.utils.dotenv import DotenvFile


def _find_recipe_auth_guide(host: str) -> dict[str, Any] | None:
    """Try to find a recipe auth_guide matching the given host."""
    try:
        from toolwright.recipes.loader import list_recipes, load_recipe

        for meta in list_recipes():
            for pattern in meta.get("hosts", []):
                if host in pattern or pattern in host:
                    recipe = load_recipe(meta["name"])
                    guide: dict[str, Any] | None = recipe.get("auth_guide")
                    if guide and guide.get("host") == host:
                        return guide
    except Exception:
        pass
    return None


def auth_setup_flow(
    *,
    root: Path,
    toolpack_path: str | None = None,
    no_probe: bool = False,
) -> None:
    """Interactive auth setup wizard.

    For each host in the toolpack:
    1. Check if auth is already configured (env var or .env file)
    2. If missing, show auth_guide from recipe (if available)
    3. Prompt for token (masked input)
    4. Probe the host to verify
    5. Save to .toolwright/.env
    """
    from toolwright.core.toolpack import load_toolpack
    from toolwright.utils.resolve import resolve_toolpack_path

    # Resolve toolpack
    try:
        tp_path = resolve_toolpack_path(explicit=toolpack_path, root=root)
    except (FileNotFoundError, click.UsageError) as e:
        click.echo(f"Error: {e}")
        return

    tp = load_toolpack(tp_path)
    hosts = tp.allowed_hosts

    if not hosts:
        click.echo("No hosts configured in this toolpack.")
        return

    display = tp.display_name or tp.toolpack_id
    click.echo()
    click.echo(f"  Auth Setup for {display}")
    click.echo()

    # Load .env file
    env_file = DotenvFile(root / ".toolwright" / ".env")
    env_file.load()

    # Check status for each host
    host_status: dict[str, tuple[str, str | None]] = {}  # host -> (status, value)
    missing_hosts: list[str] = []

    for host in hosts:
        env_var = host_to_env_var(host)
        value = os.environ.get(env_var) or env_file.get(env_var)
        if value:
            host_status[host] = ("SET", value)
        else:
            host_status[host] = ("NOT SET", None)
            missing_hosts.append(host)

    # Show summary
    need_count = len(missing_hosts)
    if need_count == 0:
        click.echo(f"  {len(hosts)} host(s) — all configured:")
        click.echo()
        for host in hosts:
            click.echo(f"  {host} {'.' * max(1, 30 - len(host))} SET")
        click.echo()
        click.echo(f"  All {len(hosts)} hosts configured.")
        return

    click.echo(f"  {need_count} host(s) need credentials:")
    click.echo()
    for host in hosts:
        status = host_status[host][0]
        dots = "." * max(1, 30 - len(host))
        click.echo(f"  {host} {dots} {status}")
    click.echo()

    # If not interactive, just show status
    interactive = sys.stdin.isatty()
    if not interactive:
        click.echo("  Non-interactive terminal — skipping prompts.")
        click.echo("  Set env vars for missing hosts to configure auth.")
        return

    configured_count = len(hosts) - need_count
    dotenv_modified = False

    for host in missing_hosts:
        env_var = host_to_env_var(host)
        click.echo(f"  --- {host} ---")

        # Show auth_guide if available
        guide = _find_recipe_auth_guide(host)
        if guide:
            if guide.get("scheme"):
                click.echo(f"  Scheme: {guide['scheme']}")
            if guide.get("create_url"):
                click.echo(f"  Create token: {guide['create_url']}")
            if guide.get("scopes_hint"):
                click.echo(f"  Scopes: {guide['scopes_hint']}")
            if guide.get("instructions"):
                click.echo(f"  Instructions: {guide['instructions']}")
            click.echo()

        click.echo(f"  Env var: {env_var}")
        click.echo()

        try:
            token = getpass.getpass("  Token: ")
        except (KeyboardInterrupt, EOFError):
            click.echo()
            click.echo("  Aborted.")
            return

        if not token:
            click.echo("  Skipped (empty input).")
            click.echo()
            continue

        # Ensure token has scheme prefix
        if not token.startswith(("Bearer ", "Basic ", "Token ")):
            token = f"Bearer {token}"

        # Probe if enabled
        if not no_probe:
            click.echo(f"  Probing {host}...", nl=False)
            status_code, description = _probe_host(host, token)
            if status_code and 200 <= status_code < 300:
                click.echo(f" {status_code} {description}")
            elif status_code in (401, 403):
                click.echo(f" {status_code} {description}")
                click.echo("  Warning: auth may be invalid.")
            elif status_code:
                click.echo(f" {status_code} {description}")
            else:
                click.echo(f" {description}")

        # Save to .env
        env_file.set(env_var, token)
        dotenv_modified = True
        configured_count += 1
        click.echo("  Saved to .toolwright/.env")
        click.echo()

    if dotenv_modified:
        env_file.save()
        DotenvFile.ensure_gitignored(env_file.path)

    click.echo(
        f"  Auth setup complete. {configured_count}/{len(hosts)} hosts configured."
    )
