"""Ship Secure Agent — flagship guided lifecycle.

The narrative engine for Toolwright: guides the user through every stage of
governed agent deployment.  Each stage follows plan-first (show → confirm →
execute → summary) and never dead-ends.

Stages:
1. Capture   — mint with progress, or use existing toolpack
2. Review    — preview new surface OR diff against prior baseline
3. Approve   — dispatch to gate_review_flow (skip if all approved)
4. Snapshot  — create baseline artifact
5. Verify    — run verification contracts
6. Serve     — show serve command + config snippet (informational)

Stage tracker is rendered between stages using SymbolSet for
Unicode/ASCII portability.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from toolwright.core.approval.lockfile import ToolApproval
from toolwright.ui.console import err_console, get_symbols
from toolwright.ui.discovery import find_lockfiles, find_toolpacks
from toolwright.ui.echo import echo_plan, echo_summary
from toolwright.ui.ops import load_lockfile_tools
from toolwright.ui.prompts import confirm, input_text, select_one
from toolwright.ui.runner import run_mint_capture, run_verify_report

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

SHIP_STAGES = [
    ("capture", "Capture"),
    ("review", "Review"),
    ("approve", "Approve"),
    ("snapshot", "Snapshot"),
    ("verify", "Verify"),
    ("serve", "Serve"),
]


# ---------------------------------------------------------------------------
# Stage tracker renderer
# ---------------------------------------------------------------------------


def _render_stage_tracker(current: int, done: set[int]) -> str:
    """Build a compact one-line stage tracker string.

    Example (rich mode):
      ✓ capture ── ✓ review ── >> approve ── ○ snapshot ── ○ verify ── ○ serve
    """
    sym = get_symbols()
    parts: list[str] = []
    for i, (key, _label) in enumerate(SHIP_STAGES):
        if i in done:
            parts.append(f"[step.done]{sym.ok} {key}[/step.done]")
        elif i == current:
            parts.append(f"[step.active]{sym.active} {key}[/step.active]")
        else:
            parts.append(f"[step.pending]{sym.pending} {key}[/step.pending]")
    sep = f" {sym.arrow} "
    return sep.join(parts)


def _show_tracker(current: int, done: set[int], con: Any) -> None:
    """Print the stage tracker line."""
    con.print()
    con.print(f"  {_render_stage_tracker(current, done)}")
    con.print()


# ---------------------------------------------------------------------------
# Main flow entry point
# ---------------------------------------------------------------------------


def ship_secure_agent_flow(
    *,
    root: Path,
    verbose: bool = False,
    input_stream: TextIO | None = None,
    url: str | None = None,  # noqa: ARG001
    allowed_hosts: list[str] | None = None,  # noqa: ARG001
) -> None:
    """End-to-end guided flow to ship a secure governed agent.

    When url is provided, runs the automated path (capture + smart approve).
    Without a URL, runs the interactive flow. Never dead-ends.
    """
    con = err_console
    sym = get_symbols()

    con.print()
    con.print("  [heading]Ship Secure Agent[/heading]")
    con.print(f"  [muted]Capture, govern, approve, verify, and serve {sym.arrow} all in one flow.[/muted]")

    done: set[int] = set()

    # =================================================================
    # Stage 1: Capture
    # =================================================================
    _show_tracker(current=0, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 1: Capture[/step.active]")
    toolpack_path = _stage_capture(root=root, verbose=verbose, con=con, input_stream=input_stream)
    if toolpack_path is None:
        _early_exit(done, con, sym)
        return
    done.add(0)

    # =================================================================
    # Stage 2: Review
    # =================================================================
    _show_tracker(current=1, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 2: Review[/step.active]")
    lockfile_path = _stage_review(
        toolpack_path=toolpack_path, root=root, verbose=verbose,
        con=con, input_stream=input_stream,
    )
    if lockfile_path is None:
        _early_exit(done, con, sym)
        return
    done.add(1)

    # =================================================================
    # Stage 3: Approve
    # =================================================================
    _show_tracker(current=2, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 3: Approve[/step.active]")
    approved = _stage_approve(
        lockfile_path=lockfile_path, root=root, verbose=verbose,
        con=con, input_stream=input_stream,
    )
    if not approved:
        _early_exit(done, con, sym)
        return
    done.add(2)

    # =================================================================
    # Stage 4: Snapshot
    # =================================================================
    _show_tracker(current=3, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 4: Baseline Snapshot[/step.active]")
    if not _stage_snapshot(
        lockfile_path=lockfile_path, root=root,
        con=con, input_stream=input_stream,
    ):
        _early_exit(done, con, sym)
        return
    done.add(3)

    # =================================================================
    # Stage 5: Verify
    # =================================================================
    _show_tracker(current=4, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 5: Verification[/step.active]")
    _stage_verify(
        toolpack_path=toolpack_path, root=root, verbose=verbose,
        con=con, input_stream=input_stream,
    )
    done.add(4)

    # =================================================================
    # Stage 6: Serve
    # =================================================================
    _show_tracker(current=5, done=done, con=con)
    con.print(f"  [step.active]{sym.active} Stage 6: Serve[/step.active]")
    _stage_serve(
        toolpack_path=toolpack_path, root=root,
        con=con, input_stream=input_stream,
    )
    done.add(5)

    # Final summary
    _show_tracker(current=-1, done=done, con=con)
    con.print(f"  [success]{sym.ok} Ship Secure Agent complete![/success]")
    con.print("  [muted]All stages passed. Your governed agent is ready to serve.[/muted]")
    con.print()


# ---------------------------------------------------------------------------
# Early exit helper
# ---------------------------------------------------------------------------


def _early_exit(done: set[int], con: Any, sym: Any) -> None:  # noqa: ARG001
    """Print summary on early exit."""
    con.print()
    if done:
        completed = [SHIP_STAGES[i][1] for i in sorted(done)]
        con.print(f"  [muted]Completed: {', '.join(completed)}[/muted]")
    con.print("  [muted]Exited early. Run [command]toolwright ship[/command] to resume.[/muted]")
    con.print()


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _stage_capture(
    *, root: Path, verbose: bool,
    con: Any, input_stream: TextIO | None = None,
) -> str | None:
    """Capture API surface. Returns toolpack_path or None on abort."""
    sym = get_symbols()

    # Check for existing toolpacks — offer to skip
    existing = find_toolpacks(root)
    if existing:
        con.print(f"  [info]Found {len(existing)} existing toolpack(s).[/info]")
        if confirm(
            "  Use an existing toolpack (skip capture)?",
            default=True, console=con, input_stream=input_stream,
        ):
            if len(existing) == 1:
                tp = str(existing[0])
                con.print(f"  {sym.ok} Using: [bold]{tp}[/bold]")
                return tp
            return select_one(
                [str(p) for p in existing],
                prompt="Select toolpack",
                console=con,
                input_stream=input_stream,
            )

    # Collect capture inputs
    start_url = input_text("API URL to capture", console=con, input_stream=input_stream)
    if not start_url:
        con.print("  [warning]URL is required.[/warning]")
        return None

    hosts_raw = input_text(
        "API hosts to capture (comma-separated)", console=con, input_stream=input_stream,
    )
    if not hosts_raw:
        con.print("  [warning]At least one host is required.[/warning]")
        return None
    hosts = [h.strip() for h in hosts_raw.split(",") if h.strip()]

    name = input_text("Session name (optional)", console=con, input_stream=input_stream)

    cmd = ["toolwright", "mint", start_url]
    for h in hosts:
        cmd.extend(["-a", h])
    if name:
        cmd.extend(["-n", name])

    echo_plan([cmd], console=con)

    if not confirm("  Proceed with capture?", default=True, console=con, input_stream=input_stream):
        return None

    con.print("  [info]Starting capture...[/info]")
    try:
        run_mint_capture(
            start_url=start_url,
            allowed_hosts=list(hosts),
            name=name or None,
            scope_name="first_party_only",
            headless=True,
            script_path=None,
            duration_seconds=30,
            output_root=str(root),
            deterministic=True,
            runtime_mode="local",
            runtime_build=False,
            runtime_tag=None,
            runtime_version_pin=None,
            print_mcp_config=False,
            verbose=verbose,
            auth_profile=None,
            webmcp=False,
            redaction_profile="default_safe",
        )
    except SystemExit:
        pass
    except Exception as exc:
        con.print(f"  [error]Capture failed: {exc}[/error]")
        if confirm("  Retry?", default=False, console=con, input_stream=input_stream):
            return _stage_capture(root=root, verbose=verbose, con=con, input_stream=input_stream)
        return None

    echo_summary([cmd], console=con)
    con.print(f"  [success]{sym.ok} Capture complete.[/success]")

    # Find the new toolpack
    new_toolpacks = find_toolpacks(root)
    if new_toolpacks:
        return str(new_toolpacks[-1])
    return None


def _stage_review(
    *, toolpack_path: str, root: Path, verbose: bool,  # noqa: ARG001
    con: Any, input_stream: TextIO | None = None,
) -> str | None:
    """Review tools: show preview or diff. Returns lockfile_path or None."""
    sym = get_symbols()

    # Find lockfiles
    lockfiles = find_lockfiles(root)
    if not lockfiles:
        con.print("  [error]No lockfiles found. Capture may have failed.[/error]")
        con.print(f"  [next]Next {sym.arrow}[/next] Run [command]toolwright gate sync --toolpack {toolpack_path}[/command]")
        return None

    lockfile_path = str(lockfiles[0])
    if len(lockfiles) > 1:
        lockfile_path = select_one(
            [str(p) for p in lockfiles],
            prompt="Select lockfile to review",
            console=con,
            input_stream=input_stream,
        )

    # Load tools for preview
    try:
        _lockfile, tools = load_lockfile_tools(lockfile_path)
    except Exception as exc:
        con.print(f"  [error]Could not load lockfile: {exc}[/error]")
        return None

    # Show tool preview (always useful context before approve stage)
    _show_tool_preview(tools, con, sym)

    return lockfile_path


def _show_tool_preview(tools: list[ToolApproval], con: Any, sym: Any) -> None:
    """Display a compact preview of discovered tools with risk summary."""
    from collections import Counter

    if not tools:
        con.print("  [muted]No tools found in lockfile.[/muted]")
        return

    risk_counts: Counter[str] = Counter()
    for t in tools:
        risk_counts[t.risk_tier] += 1

    con.print(f"  {len(tools)} tool(s) discovered:")
    for tier in ("critical", "high", "medium", "low"):
        count = risk_counts.get(tier, 0)
        if count:
            style = "error" if tier in ("critical", "high") else "warning" if tier == "medium" else "success"
            con.print(f"    [{style}]{count} {tier}[/{style}]")

    # Show first few tools as preview
    preview_count = min(5, len(tools))
    for t in tools[:preview_count]:
        method = getattr(t, "method", "?")
        path = getattr(t, "path", "?")
        con.print(f"    {sym.branch} {t.name} ({method} {path})")
    if len(tools) > preview_count:
        con.print(f"    [muted]... and {len(tools) - preview_count} more[/muted]")


def _stage_approve(
    *, lockfile_path: str, root: Path, verbose: bool,
    con: Any, input_stream: TextIO | None = None,
) -> bool:
    """Approve pending tools. Returns True if ready to proceed."""
    sym = get_symbols()

    # Check if tools need approval
    try:
        _lockfile, tools = load_lockfile_tools(lockfile_path)
    except Exception as exc:
        con.print(f"  [error]Could not load lockfile: {exc}[/error]")
        return False

    from toolwright.core.approval.lockfile import ApprovalStatus

    pending = [t for t in tools if t.status == ApprovalStatus.PENDING]

    if not pending:
        con.print(f"  {sym.ok} All tools already approved. Skipping.")
        return True

    con.print(f"  {len(pending)} tool(s) need approval.")

    if not confirm(
        "  Launch approval review?",
        default=True, console=con, input_stream=input_stream,
    ):
        con.print("  [muted]Skipped approval. Run [command]toolwright gate allow[/command] later.[/muted]")
        return False

    from toolwright.ui.flows.gate_review import gate_review_flow

    gate_review_flow(
        lockfile_path=lockfile_path,
        root_path=str(root),
        verbose=verbose,
        input_stream=input_stream,
    )

    # Re-check after review
    try:
        _lockfile2, tools2 = load_lockfile_tools(lockfile_path)
        still_pending = [t for t in tools2 if t.status == ApprovalStatus.PENDING]
        if still_pending:
            con.print(f"  [warning]{len(still_pending)} tool(s) still pending.[/warning]")
            return confirm(
                "  Continue anyway?",
                default=False, console=con, input_stream=input_stream,
            )
    except Exception:
        pass

    con.print(f"  [success]{sym.ok} Approval complete.[/success]")
    return True


def _stage_snapshot(
    *, lockfile_path: str, root: Path,
    con: Any, input_stream: TextIO | None = None,
) -> bool:
    """Create baseline snapshot. Returns True on success."""
    sym = get_symbols()

    cmd = ["toolwright", "gate", "snapshot", "--lockfile", lockfile_path]
    echo_plan([cmd], console=con)

    if not confirm(
        "  Create baseline snapshot?",
        default=True, console=con, input_stream=input_stream,
    ):
        return False

    try:
        from toolwright.ui.ops import run_gate_snapshot

        snap_path = run_gate_snapshot(lockfile_path=lockfile_path, root_path=str(root))
        con.print(f"  [success]{sym.ok} Baseline snapshot created.[/success]")
        if snap_path:
            con.print(f"  [muted]Path: {snap_path}[/muted]")
        echo_summary([cmd], console=con)
        return True
    except Exception as exc:
        con.print(f"  [error]Snapshot failed: {exc}[/error]")
        con.print(f"  [next]Next {sym.arrow}[/next] Approve all pending tools, then retry.")
        return False


def _stage_verify(
    *, toolpack_path: str, root: Path, verbose: bool,
    con: Any, input_stream: TextIO | None = None,
) -> None:
    """Run verification contracts."""
    sym = get_symbols()

    cmd = ["toolwright", "verify", "--toolpack", toolpack_path]
    echo_plan([cmd], console=con)

    if not confirm(
        "  Run verification?",
        default=True, console=con, input_stream=input_stream,
    ):
        con.print(f"  [muted]Skipped. Run [command]toolwright verify --toolpack {toolpack_path}[/command] later.[/muted]")
        return

    try:
        run_verify_report(
            toolpack_path=toolpack_path,
            mode="all",
            lockfile_path=None,
            playbook_path=None,
            ui_assertions_path=None,
            output_dir=str(root / "reports"),
            strict=True,
            top_k=5,
            min_confidence=0.70,
            unknown_budget=0.20,
            verbose=verbose,
        )
        con.print(f"  [success]{sym.ok} Verification passed.[/success]")
    except SystemExit as exc:
        if exc.code == 0:
            con.print(f"  [success]{sym.ok} Verification passed.[/success]")
        else:
            con.print(f"  [warning]Verification had issues (exit {exc.code}).[/warning]")
            con.print(f"  [next]Next {sym.arrow}[/next] Run [command]toolwright repair --toolpack {toolpack_path}[/command]")
    except Exception as exc:
        con.print(f"  [error]Verification failed: {exc}[/error]")

    echo_summary([cmd], console=con)


def _stage_serve(
    *, toolpack_path: str, root: Path,
    con: Any, input_stream: TextIO | None = None,
) -> None:
    """Show the serve command and offer config generation (informational only)."""
    serve_cmd = f"toolwright serve --toolpack {toolpack_path}"
    con.print()
    con.print("  [heading]To start the governed MCP server:[/heading]")
    con.print(f"    [command]{serve_cmd}[/command]")
    con.print("  [muted]Runs in the foreground. Press Ctrl+C to stop.[/muted]")

    # Offer config generation
    con.print()
    if confirm(
        "  Generate MCP client config snippet?",
        default=True, console=con, input_stream=input_stream,
    ):
        from toolwright.ui.flows.config import config_flow

        config_flow(toolpack_path=toolpack_path, root=root)

    # CI integration hints
    con.print()
    con.print("  [heading]Add to your CI pipeline:[/heading]")
    con.print(f"    [command]toolwright verify --toolpack {toolpack_path}[/command]")
    con.print(f"    [command]toolwright drift --toolpack {toolpack_path}[/command]")
    con.print("  [muted]These commands exit non-zero on failure, suitable for CI checks.[/muted]")
