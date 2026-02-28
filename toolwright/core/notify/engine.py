"""Notification engine for Toolwright.

Dispatches events to configured webhook channels. Supports event filtering —
each webhook can subscribe to specific event types.
"""

from __future__ import annotations

import logging
from typing import Any

from toolwright.core.notify.webhook import WebhookConfig, send_webhook

logger = logging.getLogger(__name__)


class NotificationEngine:
    """Dispatches events to configured webhooks.

    Each webhook can filter by event types. Webhooks with no events filter
    receive all events.
    """

    def __init__(self, webhooks: list[dict[str, Any]] | None = None) -> None:
        self.webhooks: list[WebhookConfig] = []
        for wh in webhooks or []:
            self.webhooks.append(
                WebhookConfig(
                    url=wh["url"],
                    events=wh.get("events", []),
                )
            )

    def matching_webhooks(self, event_type: str) -> list[WebhookConfig]:
        """Return webhooks that should receive this event type."""
        return [
            wh for wh in self.webhooks
            if not wh.events or event_type in wh.events
        ]

    async def dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        """Dispatch an event to all matching webhooks."""
        for wh in self.matching_webhooks(event_type):
            await send_webhook(wh, event_type, data)
