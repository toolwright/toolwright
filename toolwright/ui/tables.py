"""Backward-compatible re-export shim.

All logic has moved to ``toolwright.ui.views.tables``.
"""

from toolwright.ui.views.tables import (  # noqa: F401
    doctor_checklist,
    preflight_checklist,
    risk_grouped_summary,
    risk_summary_panel,
    tool_approval_table,
)
