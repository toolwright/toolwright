"""Flow registry and interactive command allowlist.

Only commands listed in INTERACTIVE_COMMANDS trigger interactive flows
on MissingParameter.  Everything else re-raises Click's normal error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    pass


class InteractiveFlow(Protocol):
    """Callable signature for interactive flows dispatched on missing params."""

    def __call__(self, *, ctx: Any, missing_param: str | None) -> None: ...


# Populated lazily by each flow module to avoid circular imports.
# Keys are Click command names.  Gate subcommands handled separately in
# commands_approval.py.
INTERACTIVE_COMMANDS: dict[str, InteractiveFlow] = {}


def register_flow(command_name: str, flow_fn: InteractiveFlow) -> None:
    """Register an interactive flow for a CLI command name."""
    INTERACTIVE_COMMANDS[command_name] = flow_fn


def _register_default_flows() -> None:
    """Register all built-in interactive flows."""
    from toolwright.ui.flows.config import config_flow
    from toolwright.ui.flows.doctor import doctor_flow
    from toolwright.ui.flows.gate_review import gate_review_flow
    from toolwright.ui.flows.init import init_flow
    from toolwright.ui.flows.repair import repair_flow
    from toolwright.ui.flows.ship import ship_secure_agent_flow

    register_flow("doctor", doctor_flow)
    register_flow("config", config_flow)
    register_flow("init", init_flow)
    register_flow("repair", repair_flow)
    register_flow("gate", gate_review_flow)
    register_flow("ship", ship_secure_agent_flow)


_register_default_flows()
