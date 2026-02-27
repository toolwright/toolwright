"""Backward-compatible re-export shim.

All logic has moved to ``toolwright.ui.ops``.  This module re-exports
everything so that existing imports continue to work.
"""

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
