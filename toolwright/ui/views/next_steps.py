"""Pure next-steps recommendation engine.

This module is the core of the TUI "narrative engine".  It takes a
snapshot of the current governance state and returns the single most
important action the user should take, plus up to 3 alternatives.

**Purity contract**: no filesystem access, no global state, no side
effects.  All inputs come via ``NextStepsInput``; output is
``NextStepsOutput``.  This makes the engine deterministic and trivially
testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Input / Output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NextStepsInput:
    """Snapshot of governance state for next-steps inference."""

    command: str
    toolpack_id: str | None = None
    lockfile_state: Literal["missing", "pending", "sealed", "stale"] = "missing"
    verification_state: Literal["not_run", "pass", "fail", "partial"] = "not_run"
    drift_state: Literal["not_checked", "clean", "warnings", "breaking"] = "not_checked"
    pending_count: int = 0
    has_baseline: bool = False
    has_mcp_config: bool = False
    has_approved_lockfile: bool = False
    has_pending_lockfile: bool = False
    last_error_code: str | None = None
    environment: Literal["local", "ci", "container"] = "local"


@dataclass(frozen=True)
class NextStep:
    """A single recommended action."""

    command: str
    label: str
    why: str


@dataclass(frozen=True)
class NextStepsOutput:
    """Primary recommendation plus alternatives."""

    primary: NextStep
    alternatives: list[NextStep]


# ---------------------------------------------------------------------------
# Toolpack-scoped command builder
# ---------------------------------------------------------------------------


def _tp(base_cmd: str, toolpack_id: str | None) -> str:
    """Append ``--toolpack <id>`` when an id is known."""
    if toolpack_id:
        return f"{base_cmd} --toolpack {toolpack_id}"
    return base_cmd


# ---------------------------------------------------------------------------
# Priority-ordered decision tree
# ---------------------------------------------------------------------------


def compute_next_steps(inp: NextStepsInput) -> NextStepsOutput:
    """Return the most important next action given current state.

    Priority order (first match wins for primary):
      1. Lockfile missing             -> gate sync
      2. Pending approvals            -> gate allow
      3. Verification failed          -> repair
      4. Drift breaking               -> investigate drift
      5. Lockfile stale (digest)      -> gate sync
      6. No baseline                  -> gate snapshot
      7. No MCP config                -> config
      8. Drift not checked            -> drift
      9. Verification not run         -> verify
     10. All green                    -> serve
    """
    candidates: list[NextStep] = []
    tid = inp.toolpack_id

    # 1. Lockfile missing
    if inp.lockfile_state == "missing":
        candidates.append(NextStep(
            command=_tp("toolwright gate sync", tid),
            label="Sync lockfile",
            why="No lockfile found — run gate sync to create one from the tool manifest",
        ))

    # 2. Pending approvals
    if inp.pending_count > 0:
        noun = "tool" if inp.pending_count == 1 else "tools"
        candidates.append(NextStep(
            command=_tp("toolwright gate allow", tid),
            label="Approve pending tools",
            why=f"{inp.pending_count} {noun} awaiting approval before serving",
        ))

    # 3. Verification failed
    if inp.verification_state == "fail":
        candidates.append(NextStep(
            command=_tp("toolwright repair", tid),
            label="Repair verification failures",
            why="Verification contracts failed — run repair to diagnose and fix",
        ))

    # 4. Drift breaking
    if inp.drift_state == "breaking":
        candidates.append(NextStep(
            command="toolwright drift",
            label="Investigate breaking drift",
            why="Breaking API surface changes detected — review before serving",
        ))

    # 5. Lockfile stale
    if inp.lockfile_state == "stale":
        candidates.append(NextStep(
            command=_tp("toolwright gate sync", tid),
            label="Re-sync lockfile",
            why="Compiled artifacts changed since last gate sync — lockfile is stale",
        ))

    # 6. No baseline
    if not inp.has_baseline and inp.has_approved_lockfile:
        candidates.append(NextStep(
            command=_tp("toolwright gate snapshot", tid),
            label="Create baseline snapshot",
            why="No baseline exists — snapshot the approved state for drift detection",
        ))

    # 7. No MCP config
    if not inp.has_mcp_config and inp.has_approved_lockfile and inp.pending_count == 0:
        candidates.append(NextStep(
            command=_tp("toolwright config", tid),
            label="Generate MCP config",
            why="No MCP client configuration found — generate a config snippet",
        ))

    # 8. Drift not checked
    if inp.drift_state == "not_checked" and inp.has_baseline:
        candidates.append(NextStep(
            command="toolwright drift",
            label="Check for drift",
            why="Drift has not been checked — detect API surface changes",
        ))

    # 9. Verification not run
    if inp.verification_state == "not_run" and inp.has_approved_lockfile:
        candidates.append(NextStep(
            command=_tp("toolwright verify", tid),
            label="Run verification",
            why="Verification contracts have not been run yet",
        ))

    # 10. All green — serve
    if not candidates:
        candidates.append(NextStep(
            command=_tp("toolwright serve", tid),
            label="Ready to serve",
            why="All checks pass — start the governed MCP server",
        ))

    # Drift warnings (non-blocking, always alternative if present)
    if inp.drift_state == "warnings" and not any("drift" in c.command for c in candidates):
        candidates.append(NextStep(
            command="toolwright drift",
            label="Review drift warnings",
            why="Non-breaking drift detected — review when convenient",
        ))

    primary = candidates[0]
    alternatives = candidates[1:4]  # max 3
    return NextStepsOutput(primary=primary, alternatives=alternatives)
