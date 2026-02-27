"""TUI view modules.

Each view exposes three render functions:
- render_rich(data) -> Renderable
- render_plain(data) -> str
- render_json(data) -> dict

Commands pick the appropriate renderer based on FlowContext.output_mode.
"""
