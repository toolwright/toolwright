"""Lifecycle management for wrapped MCP servers.

StdioLifecycleManager: Crash detection + backoff restart for stdio targets.
HttpHealthMonitor: Health pinging for HTTP targets.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StdioLifecycleManager:
    """Crash detection and backoff restart for stdio MCP servers."""

    async def restart_with_backoff(
        self,
        connection: Any,
        max_attempts: int = 5,
        base_delay: float = 1.0,
    ) -> bool:
        """Attempt to reconnect with exponential backoff.

        Returns True if reconnection succeeded, False if all attempts exhausted.
        """
        for attempt in range(1, max_attempts + 1):
            try:
                await connection.reconnect()
                logger.info("Reconnected to upstream (attempt %d)", attempt)
                return True
            except Exception as e:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Reconnect attempt %d/%d failed: %s. Retrying in %.1fs",
                    attempt,
                    max_attempts,
                    e,
                    delay,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay)

        logger.error("All %d reconnect attempts exhausted", max_attempts)
        return False


class HttpHealthMonitor:
    """Health monitoring for HTTP MCP servers via list_tools pings."""

    async def check_health(self, connection: Any) -> bool:
        """Check if the upstream server is healthy by calling list_tools.

        Returns True if healthy, False otherwise.
        """
        try:
            await connection.list_tools()
            return True
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            return False
