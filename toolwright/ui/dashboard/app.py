"""Textual full-screen dashboard for Toolwright.

Read-only, toolpack-scoped. Only reads cached artifacts (toolpack +
lockfile + last drift/verify reports). Never runs drift/verify.
Calls ops.py for all data.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static

from toolwright.ui.ops import get_status, list_tools


class StatusWidget(Static):
    """Governance status summary panel."""

    def __init__(self, toolpack_path: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._toolpack_path = toolpack_path

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        try:
            model = get_status(self._toolpack_path)
            lines = [
                f"Toolpack: {model.toolpack_id}",
                f"Tools: {model.tool_count}",
                f"Lockfile: {model.lockfile_state}",
                f"  Approved: {model.approved_count}  "
                f"Blocked: {model.blocked_count}  "
                f"Pending: {model.pending_count}",
                f"Baseline: {'exists' if model.has_baseline else 'missing'}",
                f"Drift: {model.drift_state}",
                f"Verification: {model.verification_state}",
            ]
            # Compute recommended next step
            from toolwright.ui.views.next_steps import NextStepsInput, compute_next_steps

            ns_input = NextStepsInput(
                command="dashboard",
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
            ns = compute_next_steps(ns_input)
            lines.append("")
            lines.append(f"Next → {ns.primary.label}")
            lines.append(f"  {ns.primary.command}")
            self.update("\n".join(lines))
        except Exception as exc:
            self.update(f"Error loading status: {exc}")


class ToolsTable(DataTable):
    """Sortable, filterable tools table."""

    def __init__(self, toolpack_path: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._toolpack_path = toolpack_path

    def on_mount(self) -> None:
        self.add_columns("Status", "Name", "Risk", "Method", "Path", "Host")
        self.refresh_tools()

    def refresh_tools(self) -> None:
        self.clear()
        try:
            tools = list_tools(self._toolpack_path)
            for t in tools:
                self.add_row(
                    t.status,
                    t.name,
                    t.risk_tier,
                    t.method,
                    t.path,
                    t.host,
                )
        except Exception:
            self.add_row("Error", "Could not load tools", "", "", "", "")


class ToolwrightDashboardApp(App):
    """Read-only Toolwright governance dashboard."""

    TITLE = "Toolwright Dashboard"
    CSS = """
    StatusWidget {
        dock: top;
        height: auto;
        max-height: 12;
        padding: 1 2;
        background: $surface;
        border-bottom: solid $primary;
    }
    ToolsTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, toolpack_path: str, root: str = ".toolwright", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._toolpack_path = toolpack_path
        self._root = root

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusWidget(self._toolpack_path, id="status")
        yield ToolsTable(self._toolpack_path, id="tools")
        yield Footer()

    def action_refresh(self) -> None:
        """Refresh all data from cached artifacts."""
        status = self.query_one("#status", StatusWidget)
        status.refresh_status()
        tools = self.query_one("#tools", ToolsTable)
        tools.refresh_tools()
