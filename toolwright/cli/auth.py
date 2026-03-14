"""Auth profile CLI commands."""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import Any

import click


@click.group("auth")
def auth_group() -> None:
    """Manage authentication profiles for capture."""


@auth_group.command("login")
@click.option("--profile", required=True, help="Profile name")
@click.option("--url", required=True, help="Target URL to authenticate against")
@click.option("--root", default=".toolwright", help="Toolwright root directory")
def auth_login(profile: str, url: str, root: str) -> None:
    """Launch headful browser for one-time login, saving storage state."""
    import asyncio
    from pathlib import Path

    try:
        from playwright.async_api import async_playwright as _check_pw  # noqa: F401
    except ImportError:
        click.echo("Error: playwright is required for auth login", err=True)
        click.echo("  pip install playwright && playwright install chromium", err=True)
        sys.exit(1)

    from toolwright.core.auth.profiles import AuthProfileManager

    manager = AuthProfileManager(Path(root))

    click.echo(f"Opening browser for login at {url}")
    click.echo("Complete your login, then close the browser window.")

    async def _do_login() -> dict[str, Any]:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url)

            click.echo("Waiting for browser to close...")
            with suppress(Exception):
                await page.wait_for_event("close", timeout=300_000)

            state = await context.storage_state()
            await browser.close()
            return dict(state)

    try:
        storage_state = asyncio.run(_do_login())
    except KeyboardInterrupt:
        click.echo("\nLogin cancelled.")
        sys.exit(0)
    except Exception as exc:
        click.echo(f"Error during login: {exc}", err=True)
        sys.exit(1)

    manager.create(name=profile, storage_state=storage_state, target_url=url)
    click.echo(f"Auth profile '{profile}' saved.")


@auth_group.command("status")
@click.option("--profile", required=True, help="Profile name")
@click.option("--root", default=".toolwright", help="Toolwright root directory")
def auth_status(profile: str, root: str) -> None:
    """Show the status of an auth profile."""
    from pathlib import Path

    from toolwright.core.auth.profiles import AuthProfileManager

    manager = AuthProfileManager(Path(root))
    meta = manager.get_meta(profile)
    if meta is None:
        click.echo(f"Profile '{profile}' not found.", err=True)
        sys.exit(1)

    has_state = manager.exists(profile)
    click.echo(f"Profile: {profile}")
    click.echo(f"  Target URL: {meta.get('target_url', 'unknown')}")
    click.echo(f"  Created: {meta.get('created_at', 'unknown')}")
    click.echo(f"  Last used: {meta.get('last_used_at', 'never')}")
    click.echo(f"  Storage state: {'present' if has_state else 'missing'}")


@auth_group.command("clear")
@click.option("--profile", required=True, help="Profile name")
@click.option("--root", default=".toolwright", help="Toolwright root directory")
def auth_clear(profile: str, root: str) -> None:
    """Delete an auth profile."""
    from pathlib import Path

    from toolwright.core.auth.profiles import AuthProfileManager

    manager = AuthProfileManager(Path(root))
    if manager.clear(profile):
        click.echo(f"Profile '{profile}' cleared.")
    else:
        click.echo(f"Profile '{profile}' not found.", err=True)
        sys.exit(1)


@auth_group.command("list")
@click.option("--root", default=".toolwright", help="Toolwright root directory")
def auth_list(root: str) -> None:
    """List all auth profiles."""
    from pathlib import Path

    from toolwright.core.auth.profiles import AuthProfileManager

    manager = AuthProfileManager(Path(root))
    profiles = manager.list_profiles()
    if not profiles:
        click.echo("No auth profiles found.")
        return

    for p in profiles:
        status = "ready" if p.get("has_storage_state") else "incomplete"
        click.echo(
            f"  {p['name']}  ({status})  target={p.get('target_url', '?')}"
        )


@auth_group.command("setup")
@click.option(
    "--toolpack",
    type=click.Path(),
    default=None,
    help="Path to toolpack.yaml",
)
@click.option(
    "--no-probe",
    is_flag=True,
    default=False,
    help="Skip host probing after token entry",
)
@click.option("--root", default=".", help="Project root directory")
def auth_setup(
    toolpack: str | None, no_probe: bool, root: str
) -> None:
    """Interactive auth setup — configure credentials for all hosts."""
    from pathlib import Path

    from toolwright.cli.auth_setup import auth_setup_flow

    auth_setup_flow(
        root=Path(root), toolpack_path=toolpack, no_probe=no_probe
    )
