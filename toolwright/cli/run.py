"""Run command implementation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from toolwright.cli.doctor import run_doctor
from toolwright.core.toolpack import load_toolpack
from toolwright.mcp.runtime import run_mcp_serve
from toolwright.utils.config import build_mcp_config_payload, render_config_payload
from toolwright.utils.runtime import docker_available


def run_run(
    *,
    toolpack_path: str,
    runtime: str,
    print_config_and_exit: bool,
    toolset: str | None,
    lockfile: str | None,
    base_url: str | None,
    auth_header: str | None,
    audit_log: str | None,
    dry_run: bool,
    confirm_store: str,
    allow_private_cidrs: list[str],
    allow_redirects: bool,
    unsafe_no_lockfile: bool,
    verbose: bool,
) -> None:
    """Run a toolpack locally or in a container."""
    if print_config_and_exit:
        toolpack = load_toolpack(Path(toolpack_path))
        payload = build_mcp_config_payload(
            toolpack_path=Path(toolpack_path),
            server_name=toolpack.toolpack_id,
        )
        click.echo(render_config_payload(payload, "json"))
        return

    run_doctor(toolpack_path=toolpack_path, runtime=runtime, verbose=verbose)

    toolpack = load_toolpack(Path(toolpack_path))
    mode = runtime
    if mode == "auto":
        mode = toolpack.runtime.mode if toolpack.runtime else "local"

    if mode == "local":
        run_mcp_serve(
            tools_path=None,
            toolpack_path=toolpack_path,
            toolsets_path=None,
            toolset_name=toolset,
            policy_path=None,
            lockfile_path=lockfile,
            base_url=base_url,
            auth_header=auth_header,
            audit_log=audit_log,
            dry_run=dry_run,
            confirmation_store_path=confirm_store,
            allow_private_cidrs=allow_private_cidrs,
            allow_redirects=allow_redirects,
            unsafe_no_lockfile=unsafe_no_lockfile,
            verbose=verbose,
        )
        return

    if mode != "container":
        click.echo(f"Error: unknown runtime '{mode}'", err=True)
        sys.exit(1)

    if not docker_available():
        click.echo("Error: docker not available; install Docker or use --runtime local", err=True)
        sys.exit(1)

    if toolpack.runtime is None or toolpack.runtime.container is None:
        click.echo("Error: toolpack runtime container configuration missing", err=True)
        sys.exit(1)

    container = toolpack.runtime.container
    run_wrapper = Path(toolpack_path).resolve().parent / container.run
    if not run_wrapper.exists():
        click.echo("Error: container run wrapper missing", err=True)
        sys.exit(1)

    env = os.environ.copy()
    env["TOOLWRIGHT_TOOLPACK"] = "/toolpack/toolpack.yaml"
    if toolset:
        env["TOOLWRIGHT_TOOLSET"] = toolset
    if lockfile:
        env["TOOLWRIGHT_LOCKFILE"] = lockfile
    if base_url:
        env["TOOLWRIGHT_BASE_URL"] = base_url
    if auth_header:
        env["TOOLWRIGHT_AUTH_HEADER"] = auth_header
    if audit_log:
        env["TOOLWRIGHT_AUDIT_LOG"] = audit_log
    if dry_run:
        env["TOOLWRIGHT_DRY_RUN"] = "1"
    if confirm_store:
        env["TOOLWRIGHT_CONFIRM_STORE"] = confirm_store
    if allow_private_cidrs:
        env["TOOLWRIGHT_ALLOW_PRIVATE_CIDR"] = " ".join(allow_private_cidrs)
    if allow_redirects:
        env["TOOLWRIGHT_ALLOW_REDIRECTS"] = "1"

    try:
        subprocess.run([str(run_wrapper)], check=True, env=env)
    except subprocess.CalledProcessError as exc:
        click.echo("Error: container runtime failed", err=True)
        if verbose and exc.stderr:
            click.echo(exc.stderr, err=True)
        sys.exit(1)
