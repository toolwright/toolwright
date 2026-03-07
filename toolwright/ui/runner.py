"""Backward-compatible re-export shim.

All logic has moved to ``toolwright.ui.ops``.  This module re-exports
everything so that existing imports continue to work. It also provides
UI-facing adapters for CLI-backed workflows so interactive flows do not
reach into CLI modules directly.
"""

from __future__ import annotations

from typing import Any

from toolwright.ui.ops import (  # noqa: F401
    ApproveResult,
    DoctorCheck,
    DoctorResult,
    PreflightCheck,
    PreflightResult,
    StatusModel,
    compute_fingerprint,
    get_status,
    load_lockfile_tools,
    run_doctor_checks,
    run_gate_approve,
    run_gate_reject,
    run_gate_snapshot,
    run_repair_preflight,
)
from toolwright.utils.deps import has_mcp_dependency  # noqa: F401
from toolwright.utils.runtime import docker_available  # noqa: F401


def run_mint_capture(**kwargs: Any) -> None:
    """Execute mint capture for interactive UI flows."""
    from toolwright.cli.mint import run_mint

    run_mint(**kwargs)


def run_verify_report(**kwargs: Any) -> None:
    """Execute verification for interactive UI flows."""
    from toolwright.cli.verify import run_verify

    run_verify(**kwargs)
