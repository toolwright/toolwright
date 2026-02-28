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
    """
    total_tools = sum(tools.values())
    tool_parts = " \u00b7 ".join(f"{v} {k}" for k, v in tools.items() if v)

    lines = [
        f"  Toolwright \u2014 {name}",
        f"  Tools:    {total_tools} ({tool_parts})",
    ]

    # Risk bar
    risk_parts = []
    for tier in ("low", "medium", "high", "critical"):
        count = risk_counts.get(tier, 0)
        if count:
            label = tier[:4] if tier != "critical" else "crit"
            risk_parts.append(f"{count} {label}")
    if risk_parts:
        lines.append(f"  Risk:     {' \u00b7 '.join(risk_parts)}")

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
