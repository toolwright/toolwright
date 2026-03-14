"""Auth command registration."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request

import click

from toolwright.cli.command_helpers import cli_root


def _host_to_env_var(host: str) -> str:
    """Convert a hostname to the per-host env var name.

    api.stripe.com  ->  TOOLWRIGHT_AUTH_API_STRIPE_COM
    localhost:8080  ->  TOOLWRIGHT_AUTH_LOCALHOST_8080
    """
    normalized = re.sub(r"[^A-Za-z0-9]", "_", host).upper()
    return f"TOOLWRIGHT_AUTH_{normalized}"


def _probe_host(host: str, auth_value: str | None) -> tuple[int | None, str]:
    """Make a lightweight GET to the host root to verify auth works.

    Returns (status_code, description).
    """
    url = f"https://{host}"
    headers: dict[str, str] = {"User-Agent": "Toolwright/1.0"}
    if auth_value:
        headers["Authorization"] = auth_value

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=10)  # noqa: S310
        status = resp.status
        resp.close()
        return status, "OK"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return e.code, "auth invalid"
        return e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"connection error: {e.reason}"
    except Exception as e:
        return None, f"error: {e}"


def _resolve_auth_root(ctx: click.Context, root: str | None) -> str:
    """Resolve the auth command root from CLI context or explicit override."""
    if root:
        return root
    return str(cli_root(ctx))


def register_auth_commands(*, cli: click.Group) -> None:
    """Register the auth command group and its subcommands."""

    @cli.group(invoke_without_command=True)
    @click.pass_context
    def auth(ctx: click.Context) -> None:
        """Manage authentication profiles and check auth configuration."""
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

    register_auth_check_command(auth_group=auth)

    @auth.command("login")
    @click.option("--profile", required=True, help="Profile name")
    @click.option("--url", required=True, help="Target URL to authenticate against")
    @click.option("--root", default=None, help="Toolwright root directory override")
    @click.pass_context
    def auth_login(ctx: click.Context, profile: str, url: str, root: str | None) -> None:
        """Launch headful browser for one-time login, saving storage state."""
        from toolwright.cli.auth import auth_login as _do_login

        ctx.invoke(_do_login, profile=profile, url=url, root=_resolve_auth_root(ctx, root))

    @auth.command("status")
    @click.option("--profile", required=True, help="Profile name")
    @click.option("--root", default=None, help="Toolwright root directory override")
    @click.pass_context
    def auth_status(ctx: click.Context, profile: str, root: str | None) -> None:
        """Show the status of an auth profile."""
        from toolwright.cli.auth import auth_status as _do_status

        ctx.invoke(_do_status, profile=profile, root=_resolve_auth_root(ctx, root))

    @auth.command("clear")
    @click.option("--profile", required=True, help="Profile name")
    @click.option("--root", default=None, help="Toolwright root directory override")
    @click.pass_context
    def auth_clear(ctx: click.Context, profile: str, root: str | None) -> None:
        """Delete an auth profile."""
        from toolwright.cli.auth import auth_clear as _do_clear

        ctx.invoke(_do_clear, profile=profile, root=_resolve_auth_root(ctx, root))

    @auth.command("list")
    @click.option("--root", default=None, help="Toolwright root directory override")
    @click.pass_context
    def auth_list_cmd(ctx: click.Context, root: str | None) -> None:
        """List all auth profiles."""
        from toolwright.cli.auth import auth_list as _do_list

        ctx.invoke(_do_list, root=_resolve_auth_root(ctx, root))


def register_auth_check_command(*, auth_group: click.Group) -> None:
    """Register the 'check' subcommand on the auth group."""

    @auth_group.command("check")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves if omitted)",
    )
    @click.option(
        "--no-probe",
        is_flag=True,
        default=False,
        help="Skip HTTP probing (check env vars only)",
    )
    @click.pass_context
    def auth_check(
        ctx: click.Context,
        toolpack: str | None,
        no_probe: bool,
    ) -> None:
        """Check auth configuration for the active toolpack.

        Verifies that the correct env vars are set for each host in the
        toolpack's allowed_hosts list. By default, also probes each host
        with a lightweight GET to verify the token works.

        \b
        Examples:
          toolwright auth check                  # Check auth + probe
          toolwright auth check --no-probe       # Check env vars only
          toolwright auth check --toolpack tp.yaml
        """
        from toolwright.core.toolpack import load_toolpack
        from toolwright.utils.resolve import resolve_toolpack_path

        # Resolve toolpack
        try:
            tp_path = resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx))
        except (FileNotFoundError, click.UsageError) as e:
            click.echo(str(e), err=True)
            ctx.exit(1)
            return

        # Load toolpack to get allowed_hosts
        tp = load_toolpack(tp_path)
        hosts = tp.allowed_hosts

        if not hosts:
            click.echo("No allowed_hosts configured in this toolpack.")
            return

        # Display name from toolpack
        display = tp.display_name or tp.toolpack_id
        click.echo(f"Auth Check for toolpack: {display}")
        click.echo(f"Hosts: {', '.join(hosts)}")
        click.echo()

        all_ok = True

        for host in hosts:
            click.echo(f"  {host}:")
            env_var = _host_to_env_var(host)
            per_host_val = os.environ.get(env_var)
            global_val = os.environ.get("TOOLWRIGHT_AUTH_HEADER")

            # Per-host env var
            per_host_status = "SET" if per_host_val else "NOT SET"
            click.echo(f"    Env var: {env_var} ... {per_host_status}")

            # Global fallback
            global_status = "SET (fallback)" if global_val else "NOT SET"
            click.echo(f"    Global:  TOOLWRIGHT_AUTH_HEADER ... {global_status}")

            # Determine effective auth value
            effective_auth = per_host_val or global_val

            if not effective_auth:
                all_ok = False
                click.echo()
                click.echo(f"    No auth configured for {host}")
                click.echo()
                click.echo("    Set one of:")
                click.echo(f'      export {env_var}="Bearer <token>"')
                click.echo('      export TOOLWRIGHT_AUTH_HEADER="Bearer <token>"')
                click.echo()
                continue

            # Probe if enabled
            if not no_probe:
                status_code, description = _probe_host(host, effective_auth)
                if status_code and 200 <= status_code < 300:
                    click.echo(f"    Probe:   GET https://{host} -> {status_code} {description}")
                elif status_code in (401, 403):
                    all_ok = False
                    click.echo(f"    Probe:   GET https://{host} -> {status_code} {description}")
                elif status_code:
                    click.echo(f"    Probe:   GET https://{host} -> {status_code} {description}")
                else:
                    click.echo(f"    Probe:   GET https://{host} -> {description}")

            click.echo()

        if all_ok:
            click.echo("All auth checks passed.")
        else:
            ctx.exit(1)
