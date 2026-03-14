"""Kill pillar CLI commands: kill, enable, quarantine, breaker-status."""

from __future__ import annotations

from pathlib import Path

import click

from toolwright.utils.state import resolve_root


def _default_breaker_state_path() -> Path:
    return resolve_root() / "state" / "circuit_breakers.json"


def _default_lockfile_path() -> str | None:
    """Return default lockfile path if it exists, else None."""
    candidate = Path.cwd() / "toolwright.lock.yaml"
    if candidate.exists():
        return str(candidate)
    return None


def _validate_tool_in_lockfile(tool_id: str, lockfile_path: str | None) -> None:
    """Validate that tool_id exists in the lockfile. Raise ClickException if not found."""
    if lockfile_path is None:
        return  # No lockfile specified or found — skip validation

    path = Path(lockfile_path)
    if not path.exists():
        return  # Lockfile path given but file missing — skip validation

    from toolwright.core.approval.lockfile import LockfileManager

    mgr = LockfileManager(lockfile_path=path)
    lockfile = mgr.load()

    # Check by key, tool_id, signature_id, or name
    if mgr.get_tool(tool_id) is not None:
        return

    available = sorted(t.tool_id for t in lockfile.tools.values())
    available_str = ", ".join(available) if available else "(none)"
    raise click.ClickException(
        f"Tool '{tool_id}' not found in lockfile. Available tools: {available_str}"
    )


def register_kill_commands(*, cli: click.Group) -> None:
    """Register kill-related commands on the provided CLI group."""

    @cli.command()
    @click.argument("tool_id")
    @click.option("--reason", "-r", default="manual kill", help="Reason for killing the tool.")
    @click.option(
        "--breaker-state",
        type=click.Path(),
        default=str(_default_breaker_state_path()),
        help="Path to circuit breaker state file.",
    )
    @click.option(
        "--lockfile",
        type=click.Path(),
        default=None,
        help="Path to lockfile for tool ID validation (default: auto-detect).",
    )
    @click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
    @click.pass_context
    def kill(
        ctx: click.Context,
        tool_id: str,
        reason: str,
        breaker_state: str,
        lockfile: str | None,
        yes: bool,
    ) -> None:
        """Kill a tool by forcing its circuit breaker open.

        The tool will be blocked from execution until manually re-enabled
        with `toolwright enable`.

        \b
        Examples:
          toolwright kill dangerous_tool --reason "broken endpoint"
          toolwright kill search --reason "rate limiting detected"
        """
        if not tool_id or not tool_id.strip():
            raise click.ClickException("Tool ID must not be empty.")

        lockfile_resolved = lockfile or _default_lockfile_path()
        _validate_tool_in_lockfile(tool_id, lockfile_resolved)

        no_interactive = ctx.obj.get("no_interactive_explicit", False) if ctx.obj else False
        if not yes and not no_interactive:
            click.confirm(f"Kill tool '{tool_id}'?", default=False, abort=True)

        from toolwright.core.kill.breaker import CircuitBreakerRegistry

        reg = CircuitBreakerRegistry(state_path=Path(breaker_state))
        reg.kill_tool(tool_id, reason=reason)
        click.echo(f"Tool '{tool_id}' killed (circuit breaker forced open). Reason: {reason}")

    @cli.command()
    @click.argument("tool_id")
    @click.option(
        "--breaker-state",
        type=click.Path(),
        default=str(_default_breaker_state_path()),
        help="Path to circuit breaker state file.",
    )
    @click.option(
        "--lockfile",
        type=click.Path(),
        default=None,
        help="Path to lockfile for tool ID validation (default: auto-detect).",
    )
    def enable(tool_id: str, breaker_state: str, lockfile: str | None) -> None:
        """Re-enable a killed tool by resetting its circuit breaker.

        \b
        Examples:
          toolwright enable dangerous_tool
        """
        if not tool_id or not tool_id.strip():
            raise click.ClickException("Tool ID must not be empty.")

        lockfile_resolved = lockfile or _default_lockfile_path()
        _validate_tool_in_lockfile(tool_id, lockfile_resolved)

        from toolwright.core.kill.breaker import CircuitBreakerRegistry

        reg = CircuitBreakerRegistry(state_path=Path(breaker_state))
        breaker = reg.get_breaker(tool_id)
        if breaker is None or breaker.state == "closed":
            click.echo(f"Tool '{tool_id}' is not currently killed.")
            return
        reg.enable_tool(tool_id)
        click.echo(f"Tool '{tool_id}' enabled (circuit breaker closed).")

    @cli.command()
    @click.option(
        "--breaker-state",
        type=click.Path(),
        default=str(_default_breaker_state_path()),
        help="Path to circuit breaker state file.",
    )
    def quarantine(breaker_state: str) -> None:
        """List all tools with open or half-open circuit breakers.

        Shows tools that are currently blocked or in recovery mode.

        \b
        Examples:
          toolwright quarantine
        """
        from toolwright.core.kill.breaker import CircuitBreakerRegistry

        reg = CircuitBreakerRegistry(state_path=Path(breaker_state))
        report = reg.quarantine_report()

        if not report:
            click.echo("No tools in quarantine.")
            return

        click.echo(f"{len(report)} tool(s) in quarantine:")
        for breaker in report:
            reason = breaker.kill_reason or breaker.last_failure_error or "unknown"
            click.echo(f"  {breaker.tool_id}  [{breaker.state}]  reason={reason}")

    @cli.command("breaker-status")
    @click.argument("tool_id")
    @click.option(
        "--breaker-state",
        type=click.Path(),
        default=str(_default_breaker_state_path()),
        help="Path to circuit breaker state file.",
    )
    def breaker_status(tool_id: str, breaker_state: str) -> None:
        """Show the circuit breaker status of a specific tool.

        \b
        Examples:
          toolwright breaker-status search
        """
        if not tool_id or not tool_id.strip():
            raise click.ClickException("Tool ID must not be empty.")

        from toolwright.core.kill.breaker import CircuitBreakerRegistry

        reg = CircuitBreakerRegistry(state_path=Path(breaker_state))
        breaker = reg.get_breaker(tool_id)

        if breaker is None:
            click.echo(f"No breaker for '{tool_id}' (state: closed, no failures recorded).")
            return

        click.echo(f"Tool: {breaker.tool_id}")
        click.echo(f"  State: {breaker.state}")
        click.echo(f"  Failures: {breaker.failure_count} / {breaker.failure_threshold}")
        if breaker.manual_override:
            click.echo(f"  Override: {breaker.manual_override}")
        if breaker.kill_reason:
            click.echo(f"  Kill reason: {breaker.kill_reason}")
        if breaker.last_failure_error:
            click.echo(f"  Last error: {breaker.last_failure_error}")
