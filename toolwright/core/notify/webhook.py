"""Webhook delivery for Toolwright notifications.

Supports Slack (auto-detected via URL, Block Kit format) and generic JSON webhooks.
Unreachable webhooks are handled gracefully (log warning, never crash).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    url: str
    events: list[str] = field(default_factory=list)

    @property
    def is_slack(self) -> bool:
        """Auto-detect Slack webhook URLs."""
        return "hooks.slack.com" in self.url


def build_payload(
    config: WebhookConfig,
    event_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Build the webhook payload based on the destination.

    Slack URLs get Block Kit format. Others get generic JSON.
    """
    if config.is_slack:
        text = f"*{event_type}*: {_summarize(data)}"
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                },
            ],
        }

    return {
        "event_type": event_type,
        "data": data,
        "timestamp": time.time(),
        "source": "toolwright",
    }


async def send_webhook(
    config: WebhookConfig,
    event_type: str,
    data: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> bool:
    """Send a webhook notification. Returns True on success.

    Never raises — logs a warning on failure and returns False.
    """
    import httpx

    payload = build_payload(config, event_type, data)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(config.url, json=payload)
            if response.status_code < 300:
                logger.debug("Webhook delivered to %s (status %d)", config.url, response.status_code)
                return True
            logger.warning("Webhook to %s returned status %d", config.url, response.status_code)
            return False
    except Exception as exc:
        logger.warning("Webhook to %s failed: %s", config.url, exc)
        return False


def _summarize(data: dict[str, Any]) -> str:
    """Create a short text summary from event data."""
    parts = []
    for key in ("tool", "reason", "description"):
        if key in data:
            parts.append(f"{key}={data[key]}")
    return ", ".join(parts) if parts else str(data)
