"""Wizard menu and quickstart flow.

Launched when ``toolwright`` is invoked with no arguments in an interactive terminal.

Two modes:
- **First-run**: Welcome message, project detection, offer quickstart or init.
- **Returning**: Governance health bar, dynamic context-aware menu driven by
  ``compute_next_steps()``.

The menu adapts to the current governance state — pending approvals,
failed verification, drift, etc. — and always recommends the most
important next action.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from toolwright.ui.console import err_console, get_symbols
from toolwright.ui.discovery import find_lockfiles, find_toolpacks
from toolwright.ui.prompts import confirm, input_text, select_one

# ---------------------------------------------------------------------------
# First-run detection
# ---------------------------------------------------------------------------


def _is_first_run(root: Path) -> bool:
    """Check if this is the first time the user is using Toolwright.

    True if the .toolwright directory doesn't exist or has no toolpacks.
    """
    if not root.exists():
        return True
    toolpacks = find_toolpacks(root)
    return len(toolpacks) == 0


# ---------------------------------------------------------------------------
# Governance health gathering
# ---------------------------------------------------------------------------


def _gather_governance_status(
    toolpacks: list[Path],
) -> list[Any]:
    """Gather StatusModel for each toolpack, silently skipping failures."""
    from toolwright.ui.ops import get_status

    results = []
    for tp in toolpacks:
        try:
            model = get_status(str(tp))
            results.append(model)
        except Exception:
            pass
    return sorted(results, key=_status_priority)


# ---------------------------------------------------------------------------
# Health bar rendering
# ---------------------------------------------------------------------------


def _render_health_bar(statuses: list[Any], con: Any) -> None:
    """Render a compact governance summary grouped by display name."""
    from toolwright.ui.views.status import _status_icon

    if not statuses:
        con.print("  [muted]No toolpacks found. Run [command]toolwright create[/command] to get started.[/muted]")
        return

    groups: dict[str, list[Any]] = defaultdict(list)
    for model in statuses:
        groups[model.toolpack_id or "unknown"].append(model)

    grouped = list(groups.items())
    visible = grouped[:6]

    for name, models in visible:
        pending_total = sum(model.pending_count for model in models)
        toolpack_count = len(models)
        lockfile_icon = _status_icon(_worst_lockfile_state(models))
        baseline_icon = _status_icon("current" if all(model.has_baseline for model in models) else "missing")
        drift_icon = _status_icon(_worst_drift_state(models))
        verify_icon = _status_icon(_worst_verification_state(models))

        name_part = f"  [bold]{name}[/bold]"
        if toolpack_count > 1:
            label = "toolpack" if toolpack_count == 1 else "toolpacks"
            name_part += f"  [muted]({toolpack_count} {label})[/muted]"
        if pending_total > 0:
            name_part += f"  [warning]({pending_total} pending)[/warning]"

        con.print(
            "".join(
                [
                    name_part,
                    f"  {lockfile_icon} lockfile",
                    f"  {baseline_icon} baseline",
                    f"  {drift_icon} drift",
                    f"  {verify_icon} verify",
                ]
            ),
            no_wrap=True,
        )

    hidden_groups = grouped[6:]
    if hidden_groups:
        hidden_toolpacks = sum(len(models) for _name, models in hidden_groups)
        hidden_pending = sum(
            model.pending_count for _name, models in hidden_groups for model in models
        )
        label = "toolpack" if hidden_toolpacks == 1 else "toolpacks"
        suffix = f" ({hidden_pending} pending)" if hidden_pending > 0 else ""
        con.print(f"  [muted]... and {hidden_toolpacks} more {label}{suffix}[/muted]")


def _status_priority(model: Any) -> tuple[int, int, int, int, int, str, str]:
    """Sort the wizard toward the most actionable toolpacks first."""
    if model.pending_count > 0:
        tier = 0
    elif model.verification_state == "fail":
        tier = 1
    elif model.drift_state in ("breaking", "warnings"):
        tier = 2
    elif model.lockfile_state in ("missing", "pending") or not model.has_baseline:
        tier = 3
    elif model.verification_state != "pass" or not model.has_mcp_config:
        tier = 4
    else:
        tier = 5

    verify_rank = {"fail": 0, "partial": 1, "not_run": 2, "pass": 3}
    drift_rank = {"breaking": 0, "warnings": 1, "not_checked": 2, "clean": 3}
    lockfile_rank = {"missing": 0, "pending": 1, "stale": 2, "sealed": 3}
    return (
        tier,
        -int(model.pending_count),
        verify_rank.get(model.verification_state, 99),
        drift_rank.get(model.drift_state, 99),
        lockfile_rank.get(model.lockfile_state, 99),
        str(model.toolpack_id or "").lower(),
        str(model.toolpack_path),
    )


def _worst_lockfile_state(models: list[Any]) -> str:
    ranking = {"missing": 0, "pending": 1, "stale": 2, "sealed": 3}
    return str(
        min(
        (model.lockfile_state for model in models),
        key=lambda state: ranking.get(state, 99),
        )
    )


def _worst_drift_state(models: list[Any]) -> str:
    ranking = {"breaking": 0, "warnings": 1, "not_checked": 2, "clean": 3}
    return str(
        min(
        (model.drift_state for model in models),
        key=lambda state: ranking.get(state, 99),
        )
    )


def _worst_verification_state(models: list[Any]) -> str:
    ranking = {"fail": 0, "partial": 1, "not_run": 2, "pass": 3}
    return str(
        min(
        (model.verification_state for model in models),
        key=lambda state: ranking.get(state, 99),
        )
    )


def _render_next_guidance(statuses: list[Any], con: Any, sym: Any) -> None:
    """Show the next most useful action without undercounting pending work."""
    if not statuses:
        return

    total_pending = sum(model.pending_count for model in statuses)
    pending_toolpacks = sum(1 for model in statuses if model.pending_count > 0)
    if total_pending > 0:
        tool_word = "tool" if total_pending == 1 else "tools"
        if pending_toolpacks > 1:
            pack_word = "toolpack" if pending_toolpacks == 1 else "toolpacks"
            con.print(
                f"  [next]Next {sym.arrow}[/next] {total_pending} {tool_word} awaiting approval across {pending_toolpacks} {pack_word}"
            )
        else:
            con.print(
                f"  [next]Next {sym.arrow}[/next] {total_pending} {tool_word} awaiting approval before serving"
            )
        return

    from toolwright.ui.views.next_steps import NextStepsInput, compute_next_steps

    model = statuses[0]
    inp = NextStepsInput(
        command="wizard",
        toolpack_id=model.toolpack_id,
        lockfile_state=model.lockfile_state,
        verification_state=model.verification_state,
        drift_state=model.drift_state,
        pending_count=model.pending_count,
        has_baseline=model.has_baseline,
        has_mcp_config=model.has_mcp_config,
        has_approved_lockfile=model.lockfile_state in ("sealed", "stale"),
        has_pending_lockfile=model.lockfile_state == "pending",
    )
    ns = compute_next_steps(inp)
    con.print(f"  [next]Next {sym.arrow}[/next] {ns.primary.why}")


# ---------------------------------------------------------------------------
# Dynamic menu builder
# ---------------------------------------------------------------------------


_ALWAYS_AVAILABLE = [
    ("doctor", "Check toolpack health"),
    ("config", "Generate MCP client config"),
    ("init", "Initialize Toolwright in this project"),
    ("exit", "Exit"),
]


def _build_menu(
    statuses: list[Any],
    toolpacks: list[Path],
) -> list[tuple[str, str]]:
    """Build a context-aware menu based on current governance state.

    Returns list of (key, label) tuples. The recommended action is first.
    """
    from toolwright.ui.views.next_steps import NextStepsInput, compute_next_steps

    menu: list[tuple[str, str]] = []

    # Always offer quickstart and ship
    has_toolpacks = len(toolpacks) > 0

    # If we have toolpack statuses, use next_steps to determine recommendation
    if statuses:
        model = statuses[0]
        inp = NextStepsInput(
            command="wizard",
            toolpack_id=model.toolpack_id,
            lockfile_state=model.lockfile_state,
            verification_state=model.verification_state,
            drift_state=model.drift_state,
            pending_count=model.pending_count,
            has_baseline=model.has_baseline,
            has_mcp_config=model.has_mcp_config,
            has_approved_lockfile=model.lockfile_state in ("sealed", "stale"),
            has_pending_lockfile=model.lockfile_state == "pending",
        )
        ns = compute_next_steps(inp)

        # Map next-step commands to wizard menu items
        primary_cmd = ns.primary.command.split()[1] if len(ns.primary.command.split()) > 1 else ""

        if primary_cmd == "gate" or "gate" in ns.primary.command:
            if "sync" in ns.primary.command:
                menu.append(("gate_sync", f"{ns.primary.label} (recommended)"))
            else:
                pending_total = sum(m.pending_count for m in statuses)
                pending_label = f" ({pending_total} pending)" if pending_total > 0 else ""
                menu.append(("gate", f"Review & approve tools{pending_label} (recommended)"))
        elif primary_cmd == "repair" or "repair" in ns.primary.command:
            menu.append(("repair", f"{ns.primary.label} (recommended)"))
        elif primary_cmd == "drift" or "drift" in ns.primary.command:
            menu.append(("drift", f"{ns.primary.label} (recommended)"))
        elif primary_cmd == "verify" or "verify" in ns.primary.command:
            menu.append(("verify", f"{ns.primary.label} (recommended)"))
        elif primary_cmd == "config" or "config" in ns.primary.command:
            menu.append(("config", f"{ns.primary.label} (recommended)"))
        elif primary_cmd == "serve" or "serve" in ns.primary.command:
            menu.append(("ship", "Ship Secure Agent (recommended)"))
        elif "snapshot" in ns.primary.command:
            menu.append(("snapshot", f"{ns.primary.label} (recommended)"))
        else:
            menu.append(("ship", "Ship Secure Agent (recommended)"))

    # Add standard options if not already recommended
    added_keys = {key for key, _ in menu}

    if "ship" not in added_keys:
        menu.append(("ship", "Ship Secure Agent \u2014 end-to-end governed deployment"))
    if has_toolpacks and "gate" not in added_keys and "gate_sync" not in added_keys:
        pending_total = sum(m.pending_count for m in statuses)
        pending_label = f" ({pending_total} pending)" if pending_total > 0 else ""
        menu.append(("gate", f"Review & approve tools{pending_label}"))
    if has_toolpacks and "repair" not in added_keys:
        menu.append(("repair", "Diagnose & repair toolpack issues"))
    if not has_toolpacks:
        menu.append(("quickstart", "Quick Start \u2014 capture & govern an API in minutes"))

    # Always-available utilities
    for key, label in _ALWAYS_AVAILABLE:
        if key not in added_keys:
            menu.append((key, label))

    return menu


# ---------------------------------------------------------------------------
# Main wizard flow
# ---------------------------------------------------------------------------


def wizard_flow(*, root: Path, verbose: bool = False) -> None:
    """Main wizard entry point — context-aware, adaptive."""
    if _is_first_run(root):
        _first_run_flow(root=root, verbose=verbose)
    else:
        _returning_flow(root=root, verbose=verbose)


def _first_run_flow(*, root: Path, verbose: bool) -> None:
    """First-time user experience: welcome, demo, detect, guide."""
    from toolwright.ui.views.branding import render_rich_header

    con = err_console
    sym = get_symbols()

    render_rich_header(console=con)

    con.print("  [heading]Welcome to Toolwright[/heading] — the immune system for AI tools.")
    con.print()

    # Auto-run demo to show governance in action
    try:
        from toolwright.cli.demo import run_demo

        run_demo(output_root=None, verbose=verbose, quiet=False)
    except Exception:
        # Demo failure shouldn't block the wizard
        pass

    con.print()

    # Auto-detect project context
    try:
        from toolwright.core.init.detector import detect_project

        detection = detect_project(Path.cwd())

        if detection.language != "unknown" or detection.frameworks or detection.api_specs:
            con.print("  [heading]Project detected:[/heading]")
            if detection.language != "unknown":
                con.print(f"    Language: [bold]{detection.language}[/bold]")
            if detection.frameworks:
                con.print(f"    Frameworks: [bold]{', '.join(detection.frameworks)}[/bold]")
            if detection.api_specs:
                con.print(f"    API specs: [bold]{', '.join(detection.api_specs)}[/bold]")
            con.print()
    except Exception:
        detection = None

    # Offer first-run options
    first_run_menu = [
        ("quickstart", f"Quick Start {sym.arrow} capture & govern an API in minutes"),
        ("ship", f"Ship Secure Agent {sym.arrow} end-to-end governed deployment"),
        ("init", f"Initialize Toolwright {sym.arrow} set up .toolwright/ in this project"),
        ("exit", "Exit"),
    ]

    choice = select_one(
        [key for key, _ in first_run_menu],
        labels=[label for _, label in first_run_menu],
        prompt="What would you like to do?",
        console=con,
    )

    if choice == "exit":
        return

    _dispatch(choice, root=root, verbose=verbose, detection=detection)


def _returning_flow(*, root: Path, verbose: bool) -> None:
    """Returning user experience: health bar, smart menu."""
    from toolwright.ui.views.branding import render_rich_header

    con = err_console
    sym = get_symbols()

    render_rich_header(root=str(root), console=con)

    while True:
        # Refresh governance state each loop so the wizard adapts after each action.
        toolpacks = find_toolpacks(root)
        statuses = _gather_governance_status(toolpacks)

        _render_health_bar(statuses, con)
        con.print()

        if statuses:
            _render_next_guidance(statuses, con, sym)
            con.print()

        menu = _build_menu(statuses, toolpacks)
        choice = select_one(
            [key for key, _ in menu],
            labels=[label for _, label in menu],
            prompt="What would you like to do?",
            console=con,
        )

        if choice == "exit":
            return

        _dispatch(choice, root=root, verbose=verbose)
        con.print()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(
    choice: str,
    *,
    root: Path,
    verbose: bool,
    detection: Any = None,
) -> None:
    """Dispatch to the corresponding flow."""
    con = err_console

    if choice == "quickstart":
        _quickstart_flow(root=root, verbose=verbose, detection=detection)
    elif choice == "ship":
        from toolwright.ui.flows.ship import ship_secure_agent_flow

        ship_secure_agent_flow(root=root, verbose=verbose)
    elif choice in ("gate", "gate_sync"):
        from toolwright.ui.flows.gate_review import gate_review_flow

        gate_review_flow(root_path=str(root), verbose=verbose)
    elif choice == "repair":
        from toolwright.ui.flows.repair import repair_flow

        repair_flow(root=root, verbose=verbose)
    elif choice == "config":
        from toolwright.ui.flows.config import config_flow

        config_flow(root=root)
    elif choice == "doctor":
        from toolwright.ui.flows.doctor import doctor_flow

        doctor_flow(root=root, verbose=verbose)
    elif choice == "init":
        from toolwright.ui.flows.init import init_flow

        init_flow(verbose=verbose)
    elif choice == "snapshot":
        # Run gate snapshot via CLI
        lockfiles = find_lockfiles(root)
        if lockfiles:
            from toolwright.ui.ops import run_gate_snapshot

            try:
                path = run_gate_snapshot(str(lockfiles[0]))
                con.print(f"  [success]Baseline snapshot created: {path}[/success]")
            except Exception as exc:
                con.print(f"  [error]Snapshot failed: {exc}[/error]")
        else:
            con.print("  [warning]No lockfile found. Run toolwright gate sync first.[/warning]")
    elif choice == "verify":
        toolpacks = find_toolpacks(root)
        if toolpacks:
            from toolwright.ui.flows.repair import _run_verify

            sym = get_symbols()
            _run_verify(str(toolpacks[0]), con, sym)
        else:
            con.print("  [warning]No toolpacks found.[/warning]")
    elif choice == "drift":
        con.print("  [muted]Run:[/muted] [command]toolwright drift[/command]")
    else:
        con.print(f"[warning]Unknown option: {choice}[/warning]")


# ---------------------------------------------------------------------------
# Quickstart flow with auto-detection
# ---------------------------------------------------------------------------


def _quickstart_flow(
    *,
    root: Path,
    verbose: bool,
    detection: Any = None,
) -> None:
    """Guided quickstart: detect, capture, approve, configure."""
    from toolwright.ui.echo import echo_plan

    con = err_console
    sym = get_symbols()

    con.print()
    con.print(f"  [heading]Quick Start[/heading] {sym.arrow} capture & govern an API")
    con.print()

    # Auto-detect project if not already done
    if detection is None:
        try:
            from toolwright.core.init.detector import detect_project

            detection = detect_project(Path.cwd())
        except Exception:
            detection = None

    # Pre-fill from detection
    default_url = ""
    default_hosts = ""
    if detection and detection.api_specs:
        con.print(f"  [info]Found API spec(s): {', '.join(detection.api_specs)}[/info]")
    if detection and detection.frameworks:
        con.print(f"  [info]Detected framework(s): {', '.join(detection.frameworks)}[/info]")
        # Suggest localhost for local frameworks
        local_frameworks = {"fastapi", "flask", "django", "nextjs"}
        if any(f in local_frameworks for f in detection.frameworks):
            default_url = "http://localhost:8000"
            default_hosts = "localhost"
            con.print(f"  [muted]Suggested: {default_url} (local dev server)[/muted]")
    if detection and (detection.api_specs or detection.frameworks):
        con.print()

    start_url = input_text(
        "  API URL to capture",
        default=default_url,
        console=con,
    )
    if not start_url:
        con.print("  [warning]URL is required[/warning]")
        return

    hosts_raw = input_text(
        "  API hosts to capture (comma-separated)",
        default=default_hosts,
        console=con,
    )
    if not hosts_raw:
        con.print("  [warning]At least one host is required[/warning]")
        return
    hosts = [h.strip() for h in hosts_raw.split(",") if h.strip()]

    # Auto-suggest name from host
    default_name = ""
    if hosts:
        from toolwright.ui.ops import host_to_slug

        default_name = host_to_slug(hosts[0])

    name = input_text(
        "  Name this API",
        default=default_name,
        console=con,
    )

    # Build mint command
    cmd = ["toolwright", "mint", start_url]
    for h in hosts:
        cmd.extend(["-a", h])
    if name:
        cmd.extend(["-n", name])

    echo_plan([cmd], console=con)

    if not confirm("  Proceed with capture?", default=True, console=con):
        return

    # Execute mint with progress
    try:
        from toolwright.ui.runner import run_mint_capture
        from toolwright.ui.views.progress import toolwright_progress

        with toolwright_progress("Capturing API surface..."):
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
        return

    con.print(f"  [success]{sym.ok} Capture complete.[/success]")
    con.print(f"  [next]Next {sym.arrow}[/next] [command]toolwright gate allow[/command] to review and approve tools")


def _count_pending(lockfiles: list[Path]) -> int:
    """Count total pending tools across all lockfiles."""
    count = 0
    for lf in lockfiles:
        try:
            from toolwright.core.approval import LockfileManager

            mgr = LockfileManager(lf)
            mgr.load()
            count += len(mgr.get_pending())
        except Exception:
            pass
    return count
