"""Rich startup card for the Toolwright MCP server.

Renders a compact box showing tool count, risk breakdown, context budget,
and dashboard/MCP URLs when running in HTTP mode.
"""

from __future__ import annotations


def render_startup_card(
    *,
    name: str,
    tools: dict[str, int],
    risk_counts: dict[str, int],
    context_tokens: int,
    tokens_per_tool: int,
    dashboard_url: str | None = None,
    mcp_url: str | None = None,
    auto_heal: str | None = None,
    scope_info: str | None = None,
    total_compiled: int | None = None,
    governance: dict[str, str | None] | None = None,
) -> str:
    """Render a startup card as a plain-text box.

    Args:
        name: Toolpack display name
        tools: Dict of category -> count (e.g. {"read": 5, "write": 3, "admin": 1})
        risk_counts: Dict of tier -> count (e.g. {"low": 3, "medium": 4})
        context_tokens: Total estimated context tokens
        tokens_per_tool: Average tokens per tool
        dashboard_url: Dashboard URL (HTTP mode only)
        mcp_url: MCP endpoint URL (HTTP mode only)
        auto_heal: Auto-heal level (e.g. "safe", "off")
        scope_info: Comma-separated scope names (e.g. "products, orders")
        total_compiled: Total number of compiled tools before scope filtering
        governance: Dict of layer_name -> description (None = not configured)
    """
    total_tools = sum(tools.values())
    tool_parts = " \u00b7 ".join(f"{v} {k}" for k, v in tools.items() if v)

    if scope_info and total_compiled:
        tool_line = f"  Tools:    {total_tools} (scope: {scope_info}) of {total_compiled} compiled"
    elif scope_info:
        tool_line = f"  Tools:    {total_tools} (scope: {scope_info})"
    else:
        tool_line = f"  Tools:    {total_tools} ({tool_parts})"

    lines = [
        f"  Toolwright \u2014 {name}",
        tool_line,
    ]

    # Risk bar
    risk_parts = []
    for tier in ("low", "medium", "high", "critical"):
        count = risk_counts.get(tier, 0)
        if count:
            label = tier[:4] if tier != "critical" else "crit"
            risk_parts.append(f"{count} {label}")
    if risk_parts:
        sep = " \u00b7 "
        lines.append(f"  Risk:     {sep.join(risk_parts)}")

    # Context budget
    lines.append(f"  Context:  ~{context_tokens:,} tokens \u00b7 ~{tokens_per_tool} per tool")

    # Auto-heal
    if auto_heal:
        lines.append(f"  Heal:     --auto-heal {auto_heal}")

    # URLs (HTTP mode only)
    if dashboard_url:
        lines.append(f"  Dashboard: {dashboard_url}")
    if mcp_url:
        lines.append(f"  MCP:       {mcp_url}")

    # Governance layers
    if governance is not None:
        CHECK = "\u2713"
        EMPTY = "\u25CB"
        lines.append("  Governance:")
        layer_labels = {
            "lockfile": "Lockfile enforcement (fail-closed)",
            "rules": "Behavioral rules",
            "policy": "Policy engine",
            "breakers": "Circuit breakers",
            "watch": "Watch mode",
        }
        for key in ("lockfile", "rules", "policy", "breakers", "watch"):
            value = governance.get(key)
            label = layer_labels.get(key, key)
            if value:
                lines.append(f"    {CHECK} {label}: {value}")
            else:
                lines.append(f"    {EMPTY} {label}: not configured")

    # Build box
    max_len = max(len(line) for line in lines)
    width = max_len + 2
    border_top = "\u256d" + "\u2500" * width + "\u256e"
    border_bot = "\u2570" + "\u2500" * width + "\u256f"

    boxed = [border_top]
    for line in lines:
        padded = line + " " * (width - len(line) - 1) + " "
        boxed.append(f"\u2502{padded}\u2502")
    boxed.append(border_bot)

    return "\n".join(boxed)
