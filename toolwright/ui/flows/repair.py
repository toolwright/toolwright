"""5-phase repair lifecycle — diagnose, plan, fix, verify, never dead-ends.

Phases:
1. Preflight — fast checks relevant to failure context (not full doctor)
2. Diagnosis — human-readable explanations per issue with source attribution
3. Repair Plan — patches grouped by safety (safe/approval_required/manual)
4. Guided Resolution — apply safe fixes, dispatch to gate_review for
   approval-required, show guidance for manual
5. Re-verify — run verification with progress, show pass/fail

Full ``toolwright doctor`` is always available as an escape hatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from toolwright.ui.console import err_console, get_symbols
from toolwright.ui.discovery import find_lockfiles, find_toolpacks, toolpack_labels
from toolwright.ui.ops import (
    run_doctor_checks,
    run_repair_preflight,
)
from toolwright.ui.prompts import confirm, prompt_action, select_one
from toolwright.ui.runner import run_verify_report
from toolwright.ui.views.tables import doctor_checklist, preflight_checklist

# ---------------------------------------------------------------------------
# Fix suggestion map (doctor Phase 1 -> fix commands)
# ---------------------------------------------------------------------------

_FIX_MAP: list[tuple[str, str, list[str]]] = [
    ("tools.json", "missing", ["toolwright create <recipe>  # re-create toolpack from recipe or spec"]),
    ("toolsets.yaml", "missing", ["toolwright gate sync --toolpack <path>"]),
    ("policy.yaml", "missing", ["toolwright gate sync --toolpack <path>"]),
    ("baseline.json", "missing", ["toolwright gate snapshot --lockfile <path>"]),
    ("lockfile", "missing", ["toolwright gate sync --toolpack <path>"]),
    ("artifacts digest", "mismatch", ["toolwright gate sync --toolpack <path>"]),
    ("evidence hash", "mismatch", ["toolwright verify --toolpack <path>"]),
    ("mcp dependency", "not installed", ['pip install "toolwright[mcp]"']),
    ("docker", "not available", ["Install Docker, or re-run with --runtime local"]),
    ("container:", "missing", ["toolwright create <recipe> --runtime container --runtime-build"]),
]

_SEVERITY_STYLES: dict[str, str] = {
    "critical": "error",
    "error": "error",
    "warning": "warning",
    "info": "muted",
}

_KIND_LABELS: dict[str, str] = {
    "safe": "[success]safe[/success]",
    "approval_required": "[warning]approval required[/warning]",
    "manual": "[error]manual[/error]",
}


def _suggest_fixes(name: str, detail: str) -> list[str]:
    """Return suggested fix commands for a failed check."""
    fixes: list[str] = []
    for check_sub, detail_sub, cmds in _FIX_MAP:
        if check_sub in name and detail_sub in detail.lower():
            fixes.extend(cmds)
    if not fixes:
        fixes.append(detail)
    return fixes


def _has_pending_tools(toolpack_path: str) -> bool:
    """Check if the toolpack has any pending lockfile with unapproved tools."""
    try:
        from toolwright.ui.ops import load_lockfile_tools

        tp_dir = Path(toolpack_path).parent
        lockfiles = list(tp_dir.glob("**/*.pending.*"))
        for lf in lockfiles:
            _, tools = load_lockfile_tools(str(lf))
            from toolwright.core.approval.lockfile import ApprovalStatus

            if any(t.status == ApprovalStatus.PENDING for t in tools):
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Main flow entry point
# ---------------------------------------------------------------------------


def repair_flow(
    *,
    toolpack_path: str | None = None,
    root: Path | None = None,
    verbose: bool = False,
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
    input_stream: Any = None,
) -> None:
    """5-phase repair lifecycle: preflight, diagnose, plan, fix, verify.

    Never dead-ends — every failure path offers a concrete next action.
    """
    con = err_console
    sym = get_symbols()

    if root is None:
        root = Path(".toolwright")

    con.print()
    con.print(f"  [heading]Repair[/heading] {sym.arrow} diagnose & fix")
    con.print()

    # Resolve toolpack
    if toolpack_path is None:
        candidates = find_toolpacks(root)
        if not candidates:
            con.print("[error]No toolpacks found. Run toolwright create to get started.[/error]")
            return
        if len(candidates) == 1:
            toolpack_path = str(candidates[0])
            con.print(f"  Found toolpack: [bold]{toolpack_labels(candidates, root=root)[0]}[/bold]")
        else:
            toolpack_path = select_one(
                [str(p) for p in candidates],
                labels=toolpack_labels(candidates, root=root),
                prompt="Select toolpack to diagnose",
                console=con,
                input_stream=input_stream,
            )

    # ===================================================================
    # Phase 1: Preflight (fast, focused checks)
    # ===================================================================
    con.print("\n  [heading]Phase 1: Preflight[/heading]")

    preflight = run_repair_preflight(toolpack_path)
    table = preflight_checklist(preflight.checks)
    con.print(table)

    if not preflight.all_passed:
        failed = [c for c in preflight.checks if not c.passed]
        con.print(f"\n  [warning]{len(failed)} preflight issue(s):[/warning]")
        for check in failed:
            con.print(f"    [error]{check.name}[/error]: {check.detail}")
            fixes = _suggest_fixes(check.name, check.detail)
            for fix in fixes:
                con.print(f"      [command]{fix}[/command]")

        # Offer full doctor as escape hatch
        action = prompt_action(
            {"c": "continue anyway", "d": "full doctor", "q": "quit"},
            prompt="Preflight issues detected",
            console=con,
            input_stream=input_stream,
        )
        if action == "q":
            return
        if action == "d":
            _run_full_doctor(toolpack_path, con)

    con.print(f"  [success]{sym.ok} Preflight passed[/success]")

    # ===================================================================
    # Phase 2: Diagnosis (deep RepairEngine analysis)
    # ===================================================================
    con.print("\n  [heading]Phase 2: Diagnosis[/heading]")

    engine_report = _run_engine_diagnosis(toolpack_path, con)
    has_issues = engine_report is not None and engine_report.diagnosis.total_issues > 0

    if not has_issues:
        con.print(f"  [success]{sym.ok} No issues found in audit logs, drift, or verify reports.[/success]")

        # Check for pending tools
        if _has_pending_tools(toolpack_path):
            con.print(f"\n  [info]Pending tools detected {sym.arrow} tools need approval.[/info]")
            if confirm(
                "  Jump to gate review?",
                default=True,
                console=con,
                input_stream=input_stream,
            ):
                from toolwright.ui.flows.gate_review import gate_review_flow

                lockfiles = find_lockfiles(root)
                lf = str(lockfiles[0]) if lockfiles else None
                gate_review_flow(
                    lockfile_path=lf,
                    root_path=str(root),
                    verbose=verbose,
                    input_stream=input_stream,
                )
        return

    # ===================================================================
    # Phase 3: Repair Plan (patches grouped by safety)
    # ===================================================================
    con.print("\n  [heading]Phase 3: Repair Plan[/heading]")

    plan = engine_report.patch_plan
    if plan.total_patches == 0:
        con.print("  [muted]No automated fixes available.[/muted]")
    else:
        safe_patches = [p for p in plan.patches if p.kind == "safe"]
        approval_patches = [p for p in plan.patches if p.kind == "approval_required"]
        manual_patches = [p for p in plan.patches if p.kind == "manual"]

        if safe_patches:
            con.print(f"\n  [success]Safe fixes ({len(safe_patches)}):[/success]")
            for p in safe_patches:
                con.print(f"    {sym.ok} {p.title}")
                con.print(f"      [command]{p.cli_command}[/command]")

        if approval_patches:
            con.print(f"\n  [warning]Approval required ({len(approval_patches)}):[/warning]")
            for p in approval_patches:
                con.print(f"    {sym.warning} {p.title}")
                con.print(f"      [command]{p.cli_command}[/command]")

        if manual_patches:
            con.print(f"\n  [error]Manual investigation ({len(manual_patches)}):[/error]")
            for p in manual_patches:
                con.print(f"    {sym.fail} {p.title}")
                con.print(f"      {p.description}")
                if p.risk_note:
                    con.print(f"      [muted]Risk: {p.risk_note}[/muted]")

    # ===================================================================
    # Phase 4: Guided Resolution
    # ===================================================================
    con.print("\n  [heading]Phase 4: Guided Resolution[/heading]")

    if plan.safe_count > 0 and confirm(
        f"  Apply {plan.safe_count} safe fix(es)?",
        default=True,
        console=con,
        input_stream=input_stream,
    ):
        for p in [p for p in plan.patches if p.kind == "safe"]:
            con.print(f"    [command]{p.cli_command}[/command]")
        con.print("  [muted]Run the commands above to apply safe fixes.[/muted]")

    if plan.approval_required_count > 0:
        con.print(f"\n  {plan.approval_required_count} fix(es) need gate approval.")
        if confirm(
            "  Jump to gate review?",
            default=True,
            console=con,
            input_stream=input_stream,
        ):
            from toolwright.ui.flows.gate_review import gate_review_flow

            lockfiles = find_lockfiles(root)
            lf = str(lockfiles[0]) if lockfiles else None
            gate_review_flow(
                lockfile_path=lf,
                root_path=str(root),
                verbose=verbose,
                input_stream=input_stream,
            )

    if plan.manual_count > 0:
        con.print(f"\n  [warning]{plan.manual_count} issue(s) require manual investigation.[/warning]")

    # ===================================================================
    # Phase 5: Re-verify
    # ===================================================================
    con.print("\n  [heading]Phase 5: Re-verify[/heading]")

    if confirm(
        "  Run verification to check current state?",
        default=True,
        console=con,
        input_stream=input_stream,
    ):
        _run_verify(toolpack_path, con, sym)
    else:
        con.print(f"  [next]Next {sym.arrow}[/next] toolwright verify --toolpack {toolpack_path}")


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _run_full_doctor(toolpack_path: str, con: Any) -> None:
    """Run full doctor checks and display results."""
    con.print("\n  [heading]Full Doctor[/heading]")
    try:
        result = run_doctor_checks(toolpack_path)
    except (FileNotFoundError, ValueError) as exc:
        con.print(f"  [error]Doctor failed: {exc}[/error]")
        return

    check_tuples = [(c.name, c.passed, c.detail) for c in result.checks]
    table = doctor_checklist(check_tuples)
    con.print(table)

    failures = [c for c in result.checks if not c.passed]
    if not failures:
        con.print("  [success]All doctor checks passed.[/success]")
    else:
        con.print(f"  [warning]{len(failures)} issue(s) found.[/warning]")
        for check in failures:
            con.print(f"    [error]{check.name}[/error]: {check.detail}")
            fixes = _suggest_fixes(check.name, check.detail)
            for fix in fixes:
                con.print(f"      [command]{fix}[/command]")


def _run_engine_diagnosis(toolpack_path: str, con: Any) -> Any:
    """Run RepairEngine with auto-discover and display structured results."""
    try:
        from toolwright.core.repair.engine import RepairEngine
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        tp_path = Path(toolpack_path)
        toolpack = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=tp_path)
    except Exception as exc:
        con.print(f"  [warning]Could not load toolpack for deep diagnosis: {exc}[/warning]")
        return None

    try:
        engine = RepairEngine(
            toolpack=toolpack,
            toolpack_path=Path(toolpack_path),
            resolved=resolved,
        )
        report = engine.run(context_paths=[], auto_discover=True)
    except Exception as exc:
        con.print(f"  [warning]Engine diagnosis failed: {exc}[/warning]")
        return None

    if report.diagnosis.total_issues == 0:
        return report

    con.print(f"  {report.diagnosis.total_issues} issue(s) found:\n")

    for item in report.diagnosis.items:
        sev_style = _SEVERITY_STYLES.get(item.severity, "muted")
        con.print(f"    [{sev_style}]{item.severity.upper()}[/{sev_style}]  {item.title}")
        con.print(f"      {item.description}")

    if report.diagnosis.context_files_used:
        con.print("\n  [muted]Context files analyzed:[/muted]")
        for f in report.diagnosis.context_files_used:
            con.print(f"    [muted]{f}[/muted]")

    return report


def _run_verify(toolpack_path: str, con: Any, sym: Any) -> None:
    """Run verification and display results."""
    try:
        con.print("  Running verification...")
        run_verify_report(
            toolpack_path=toolpack_path,
            mode="contracts",
            lockfile_path=None,
            playbook_path=None,
            ui_assertions_path=None,
            output_dir=None,
            strict=True,
            top_k=5,
            min_confidence=0.70,
            unknown_budget=0.20,
            verbose=False,
        )
        con.print(f"  [success]{sym.ok} Verification complete.[/success]")
    except SystemExit as exc:
        if exc.code == 0:
            con.print(f"  [success]{sym.ok} Verification passed.[/success]")
        else:
            con.print(f"  [error]{sym.fail} Verification failed (exit {exc.code}).[/error]")
            con.print(f"  [next]Next {sym.arrow}[/next] Investigate failures, then re-run toolwright repair")
    except Exception as exc:
        con.print(f"  [error]Verification error: {exc}[/error]")
        con.print(f"  [next]Next {sym.arrow}[/next] toolwright verify --toolpack {toolpack_path}")
