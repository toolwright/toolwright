"""Approximate token counting for context budget estimation.

Uses a word-based heuristic (words * 1.3) by default. Optional tiktoken
integration via `pip install "toolwright[tokens]"` for precise counting.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count using word-based approximation.

    Heuristic: tokens ~= words * 1.3 (accounts for subword tokenization).
    """
    if not text:
        return 0
    words = text.split()
    return round(len(words) * 1.3)


def format_context_budget(*, total_tokens: int, tool_count: int) -> str:
    """Format a human-readable context budget string."""
    per_tool = round(total_tokens / tool_count) if tool_count > 0 else 0
    return f"Context: ~{total_tokens:,} tokens ({tool_count} tools · ~{per_tool} per tool)"
