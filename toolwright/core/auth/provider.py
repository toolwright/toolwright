"""Token provider protocol — design-only interface for runtime auth.

This defines the abstraction for runtime token handling.
Implement adapters after beta when enterprise users demand it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from toolwright.models.decision import DecisionContext


@runtime_checkable
class TokenProvider(Protocol):
    """Abstract interface for runtime auth token management.

    Implementations should handle token lifecycle:
    - Fetching access tokens for tool invocations
    - Refreshing expired tokens
    - Revoking tokens on demand

    This protocol is defined but not implemented in beta.
    Runtime token handler (BFF pattern) comes in a future release.
    """

    async def get_access_token(self, tool_id: str, context: DecisionContext) -> str:
        """Get an access token for a tool invocation."""
        ...

    async def refresh_if_needed(self, tool_id: str) -> bool:
        """Refresh the token if it's expired or about to expire.

        Returns True if refresh succeeded.
        """
        ...

    async def revoke(self, tool_id: str) -> None:
        """Revoke the current token for a tool."""
        ...
