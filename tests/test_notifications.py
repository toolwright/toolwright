"""Tests for notification engine and webhooks (Sprint 5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# NotificationEngine
# ---------------------------------------------------------------------------


class TestNotificationEngine:
    """Core notification dispatch."""

    def test_engine_registers_webhooks(self) -> None:
        """Engine should accept webhook configs."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hooks.slack.com/services/T/B/x", "events": ["drift_detected"]},
        ])
        assert len(engine.webhooks) == 1

    def test_engine_filters_by_event_type(self) -> None:
        """Engine should only dispatch to webhooks subscribed to the event."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hook1.example.com", "events": ["drift_detected"]},
            {"url": "https://hook2.example.com", "events": ["quarantined"]},
        ])
        matching = engine.matching_webhooks("drift_detected")
        assert len(matching) == 1
        assert matching[0].url == "https://hook1.example.com"

    def test_engine_all_events_catches_all(self) -> None:
        """Webhook with no events filter should match everything."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hook.example.com"},
        ])
        assert len(engine.matching_webhooks("any_event")) == 1

    @pytest.mark.asyncio
    async def test_engine_dispatch_calls_webhook(self) -> None:
        """Engine dispatch should call webhook sender."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hook.example.com", "events": ["drift_detected"]},
        ])

        with patch("toolwright.core.notify.engine.send_webhook", new_callable=AsyncMock) as mock_send:
            await engine.dispatch("drift_detected", {"tool": "get_users"})
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_engine_dispatch_skips_non_matching(self) -> None:
        """Engine should not dispatch to webhooks not subscribed to the event."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hook.example.com", "events": ["quarantined"]},
        ])

        with patch("toolwright.core.notify.engine.send_webhook", new_callable=AsyncMock) as mock_send:
            await engine.dispatch("drift_detected", {"tool": "get_users"})
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook sender
# ---------------------------------------------------------------------------


class TestWebhookSender:
    """Webhook HTTP delivery."""

    @pytest.mark.asyncio
    async def test_send_webhook_posts_json(self) -> None:
        """send_webhook should POST JSON to the URL."""
        import httpx

        from toolwright.core.notify.webhook import WebhookConfig, send_webhook

        config = WebhookConfig(url="https://hook.example.com")

        mock_response = httpx.Response(200, request=httpx.Request("POST", "https://hook.example.com"))
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await send_webhook(config, "drift_detected", {"tool": "get_users"})
            assert result is True
            mock_client.post.assert_called_once()

    def test_slack_url_detected(self) -> None:
        """Slack URLs should be auto-detected."""
        from toolwright.core.notify.webhook import WebhookConfig

        config = WebhookConfig(url="https://hooks.slack.com/services/T/B/x")
        assert config.is_slack is True

    def test_non_slack_url(self) -> None:
        """Non-Slack URLs should not be detected as Slack."""
        from toolwright.core.notify.webhook import WebhookConfig

        config = WebhookConfig(url="https://hook.example.com")
        assert config.is_slack is False

    def test_slack_payload_format(self) -> None:
        """Slack webhook should use Block Kit format."""
        from toolwright.core.notify.webhook import WebhookConfig, build_payload

        config = WebhookConfig(url="https://hooks.slack.com/services/T/B/x")
        payload = build_payload(config, "drift_detected", {"tool": "get_users"})
        assert "blocks" in payload

    def test_generic_payload_format(self) -> None:
        """Generic webhook should use simple JSON format."""
        from toolwright.core.notify.webhook import WebhookConfig, build_payload

        config = WebhookConfig(url="https://hook.example.com")
        payload = build_payload(config, "drift_detected", {"tool": "get_users"})
        assert "event_type" in payload
        assert payload["event_type"] == "drift_detected"

    @pytest.mark.asyncio
    async def test_unreachable_webhook_does_not_crash(self) -> None:
        """Unreachable webhook should log warning, not crash."""
        from toolwright.core.notify.webhook import WebhookConfig, send_webhook

        config = WebhookConfig(url="https://unreachable.invalid")

        # Should not raise — graceful handling
        result = await send_webhook(config, "test_event", {"key": "value"})
        assert result is False
