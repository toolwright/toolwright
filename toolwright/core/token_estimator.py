"""Token consumption estimator for different transport modes.

Computes per-tool and context overhead token estimates for MCP (stdio),
MCP (scoped), CLI, and REST transports.  Used by ``toolwright estimate-tokens``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rough chars-per-token ratio (GPT/Claude tokenizers average ~4 chars/token)
_CHARS_PER_TOKEN = 4

# Fallback per-tool token count when we can't compute from schema
_DEFAULT_MCP_TOKENS_PER_TOOL = 500

# CLI: tool name + flags → small overhead
_CLI_TOKENS_PER_TOOL = 50
_CLI_CONTEXT_BASE = 100  # system prompt overhead for CLI dispatch

# REST: JSON request body overhead
_REST_TOKENS_PER_TOOL = 30
_REST_CONTEXT_BASE = 50  # minimal framing


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TransportEstimate:
    """Token estimate for a single transport mode."""

    transport: str
    tokens_per_tool: int
    context_overhead: int

    @property
    def total(self) -> int:
        return self.tokens_per_tool + self.context_overhead


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


@dataclass
class TokenEstimator:
    """Estimate token consumption across transport modes for a toolpack."""

    name: str
    tool_count: int
    categories: dict[str, int]
    _per_tool_tokens: list[int] = field(repr=False, default_factory=list)
    _largest_group_size: int | None = field(repr=False, default=None)
    _has_groups: bool = field(repr=False, default=False)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_manifest(
        cls,
        manifest: dict[str, Any],
        *,
        groups_data: dict[str, Any] | None = None,
    ) -> TokenEstimator:
        """Build an estimator from a tools.json manifest dict.

        Parameters
        ----------
        manifest:
            Parsed tools.json content (must contain ``actions`` list).
        groups_data:
            Parsed groups.json content (optional).  When present the
            estimator adds an ``MCP (scoped)`` row using the largest group.
        """
        actions: list[dict[str, Any]] = manifest.get("actions", [])
        name = manifest.get("name", "toolpack")

        # Categorise
        categories: dict[str, int] = {}
        per_tool_tokens: list[int] = []

        for action in actions:
            method = action.get("method", "GET").upper()
            if method == "GET":
                cat = "read"
            elif method in ("POST", "PUT", "PATCH"):
                cat = "write"
            else:
                cat = "admin"
            categories[cat] = categories.get(cat, 0) + 1

            # Estimate tokens for this tool definition
            chars = len(action.get("name", ""))
            chars += len(action.get("description", ""))
            schema = action.get("input_schema")
            if schema:
                chars += len(json.dumps(schema))
            tokens = max(chars // _CHARS_PER_TOKEN, 1)
            per_tool_tokens.append(tokens)

        # Groups
        largest_group_size: int | None = None
        has_groups = False
        if groups_data:
            groups = groups_data.get("groups", [])
            if groups:
                has_groups = True
                largest_group_size = max(len(g.get("tools", [])) for g in groups)

        return cls(
            name=name,
            tool_count=len(actions),
            categories=categories,
            _per_tool_tokens=per_tool_tokens,
            _largest_group_size=largest_group_size,
            _has_groups=has_groups,
        )

    # ------------------------------------------------------------------
    # Estimates
    # ------------------------------------------------------------------

    def _avg_per_tool(self) -> int:
        """Average per-tool token count from schema analysis."""
        if not self._per_tool_tokens:
            return _DEFAULT_MCP_TOKENS_PER_TOOL
        return max(sum(self._per_tool_tokens) // len(self._per_tool_tokens), 1)

    def estimates(self) -> list[TransportEstimate]:
        """Return token estimates for each transport mode."""
        avg = self._avg_per_tool()
        total_mcp_context = sum(self._per_tool_tokens) if self._per_tool_tokens else 0

        results: list[TransportEstimate] = []

        # MCP (stdio) — all tools loaded into context
        results.append(
            TransportEstimate(
                transport="MCP (stdio)",
                tokens_per_tool=avg,
                context_overhead=total_mcp_context,
            )
        )

        # MCP (scoped) — only largest group loaded
        if self._has_groups and self._largest_group_size is not None:
            scoped_fraction = (
                self._largest_group_size / self.tool_count if self.tool_count > 0 else 1.0
            )
            scoped_context = int(total_mcp_context * scoped_fraction)
            results.append(
                TransportEstimate(
                    transport="MCP (scoped)",
                    tokens_per_tool=avg,
                    context_overhead=scoped_context,
                )
            )

        # CLI
        cli_context = _CLI_CONTEXT_BASE + self.tool_count * 5  # brief tool list
        results.append(
            TransportEstimate(
                transport="CLI",
                tokens_per_tool=_CLI_TOKENS_PER_TOOL,
                context_overhead=cli_context,
            )
        )

        # REST
        rest_context = _REST_CONTEXT_BASE + self.tool_count * 2
        results.append(
            TransportEstimate(
                transport="REST",
                tokens_per_tool=_REST_TOKENS_PER_TOOL,
                context_overhead=rest_context,
            )
        )

        return results

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def recommendations(self) -> list[str]:
        """Generate actionable recommendations based on estimates."""
        recs: list[str] = []
        estimates = self.estimates()

        mcp_full = next((e for e in estimates if e.transport == "MCP (stdio)"), None)
        mcp_scoped = next((e for e in estimates if e.transport == "MCP (scoped)"), None)
        cli_est = next((e for e in estimates if e.transport == "CLI"), None)
        rest_est = next((e for e in estimates if e.transport == "REST"), None)

        if mcp_full and mcp_scoped and mcp_full.context_overhead > 0:
            reduction = int((1 - mcp_scoped.context_overhead / mcp_full.context_overhead) * 100)
            if reduction > 0:
                recs.append(f"Use --scope to reduce MCP context by {reduction}%")

        if mcp_full and cli_est and mcp_full.total > 0:
            savings = int((1 - cli_est.total / mcp_full.total) * 100)
            if savings > 0:
                recs.append(f"CLI transport uses {savings}% fewer tokens than full MCP")

        if rest_est:
            recs.append("REST is optimal for programmatic integrations")

        return recs
