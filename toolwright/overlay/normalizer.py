"""Convert MCP CallToolResult into the pipeline envelope format.

The RequestPipeline's _process_response() expects:
    {"status_code": int, "data": Any, "action": str}

This module bridges MCP's CallToolResult (content blocks + isError flag)
into that envelope.
"""

from __future__ import annotations

import json
from typing import Any


def normalize_mcp_result(tool_name: str, result: Any) -> dict[str, Any]:
    """Convert an MCP CallToolResult to the pipeline envelope format.

    Handles:
    - Single text content → parse JSON if valid, else string
    - Multiple text blocks → concatenate with newlines
    - Non-text content (image, resource) → graceful placeholder
    - Mixed content → extract text, skip non-text
    - Error results → status_code 500
    - Empty content → empty string
    """
    is_error = getattr(result, "isError", False)
    content_blocks = getattr(result, "content", []) or []

    # Extract text from content blocks
    text_parts: list[str] = []
    for block in content_blocks:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        else:
            # Non-text content: note its presence but don't crash
            text_parts.append(f"[{block_type} content]")

    combined = "\n".join(text_parts) if text_parts else ""

    # For a single text block, try JSON parsing
    data: Any = combined
    if len(text_parts) == 1 and content_blocks and getattr(content_blocks[0], "type", "") == "text":
        try:
            data = json.loads(text_parts[0])
        except (json.JSONDecodeError, ValueError):
            data = text_parts[0]

    return {
        "status_code": 500 if is_error else 200,
        "data": data,
        "action": tool_name,
    }
