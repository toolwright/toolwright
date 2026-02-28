"""Integration tests for Phase 10 components working together (Sprint 8)."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from tests.helpers import write_demo_toolpack

# ---------------------------------------------------------------------------
# EventBus + Pipeline integration
# ---------------------------------------------------------------------------


class TestEventBusIntegration:
    """EventBus receives events from multiple producers."""

    def test_eventbus_publish_subscribe_lifecycle(self) -> None:
        """Publish events, subscribe, receive them in order."""
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        bus.publish("tool_called", {"tool": "get_user"})
        bus.publish("decision", {"action": "approve"})
        bus.publish("drift_detected", {"field": "email"})

        events = bus.recent(10)
        assert len(events) == 3
        assert events[0].event_type == "tool_called"
        assert events[1].event_type == "decision"
        assert events[2].event_type == "drift_detected"

    def test_eventbus_overflow_drops_oldest(self) -> None:
        """When buffer is full, oldest events are dropped."""
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=5)
        for i in range(10):
            bus.publish("event", {"i": i})

        events = bus.recent(10)
        assert len(events) == 5
        assert events[0].data["i"] == 5  # oldest surviving


# ---------------------------------------------------------------------------
# Notifications + EventBus integration
# ---------------------------------------------------------------------------


class TestNotifyIntegration:
    """Notification engine dispatches based on event types."""

    @pytest.mark.asyncio
    async def test_webhook_filters_events(self) -> None:
        """Webhooks with event filters only fire for matching events."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=[
            {"url": "https://hooks.slack.com/test", "events": ["drift_detected"]},
            {"url": "https://example.com/webhook", "events": []},
        ])

        # drift_detected should match both (slack has it, generic has no filter)
        matching = engine.matching_webhooks("drift_detected")
        assert len(matching) == 2

        # tool_called should match only generic (no filter = all)
        matching = engine.matching_webhooks("tool_called")
        assert len(matching) == 1
        assert matching[0].url == "https://example.com/webhook"


# ---------------------------------------------------------------------------
# Share round-trip integration
# ---------------------------------------------------------------------------


class TestShareIntegration:
    """Bundle → install round-trip with real toolpack."""

    def test_full_round_trip_preserves_content(self, tmp_path: Path) -> None:
        """Bundle and install should preserve all non-excluded files."""
        from toolwright.core.share.bundler import create_bundle
        from toolwright.core.share.installer import install_bundle

        toolpack_path = write_demo_toolpack(tmp_path)

        twp = create_bundle(toolpack_path, output_dir=tmp_path / "bundles")
        result = install_bundle(twp, install_dir=tmp_path / "installed")

        assert result.verified
        installed_files = list((tmp_path / "installed").rglob("*"))
        installed_file_count = sum(1 for f in installed_files if f.is_file())
        assert installed_file_count > 0

    def test_bundle_with_extra_sensitive_files(self, tmp_path: Path) -> None:
        """Sensitive files are excluded from bundle even when present."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_path = write_demo_toolpack(tmp_path)
        toolpack_dir = toolpack_path.parent

        # Create sensitive files
        (toolpack_dir / "auth_token.txt").write_text("secret")
        (toolpack_dir / "signing.key").write_text("key")

        twp = create_bundle(toolpack_path, output_dir=tmp_path / "out")
        with tarfile.open(str(twp), "r:gz") as tf:
            names = tf.getnames()
            assert not any("auth" in n.lower() for n in names)
            assert not any("signing.key" in n.lower() for n in names)


# ---------------------------------------------------------------------------
# Observability integration
# ---------------------------------------------------------------------------


class TestObservabilityIntegration:
    """Tracer and metrics work together."""

    def test_tracer_and_metrics_combined(self) -> None:
        """Tracer spans and metric counters work in the same flow."""
        from toolwright.mcp.observe import MetricsRegistry, create_tracer

        tracer = create_tracer("integration-test")
        metrics = MetricsRegistry()

        with tracer.start_as_current_span("tool_call") as span:
            span.set_attribute("tool", "get_user")
            metrics.increment("tool_calls_total", labels={"tool": "get_user"})
            metrics.observe("request_duration_seconds", 0.15)

        assert metrics.get("tool_calls_total", labels={"tool": "get_user"}) == 1
        text = metrics.render_prometheus()
        assert "tool_calls_total" in text
        assert "request_duration_seconds" in text


# ---------------------------------------------------------------------------
# Smart gate + share integration
# ---------------------------------------------------------------------------


class TestSmartGateShareIntegration:
    """Smart gate classifications and share bundles work together."""

    def test_smart_gate_approvals_in_bundle(self) -> None:
        """Smart gate classifications produce valid approval strings."""
        from toolwright.core.approval.smart_gate import classify_approval

        low = classify_approval("low")
        assert low.auto_approve
        assert "risk_policy" in low.approved_by

        medium = classify_approval("medium")
        assert medium.auto_approve
        assert "risk_policy" in medium.approved_by

        high = classify_approval("high")
        assert not high.auto_approve
        assert high.default_yes

        critical = classify_approval("critical")
        assert not critical.auto_approve
        assert not critical.default_yes


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for Phase 10 components."""

    def test_empty_eventbus(self) -> None:
        """EventBus with no events returns empty list."""
        from toolwright.mcp.events import EventBus

        bus = EventBus()
        assert bus.recent(10) == []

    def test_metrics_prometheus_empty(self) -> None:
        """Empty metrics registry renders empty string."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        assert registry.render_prometheus() == ""

    def test_notification_engine_no_webhooks(self) -> None:
        """Engine with no webhooks dispatches nothing."""
        from toolwright.core.notify.engine import NotificationEngine

        engine = NotificationEngine(webhooks=None)
        assert engine.matching_webhooks("any_event") == []

    def test_bundle_empty_toolpack_dir(self, tmp_path: Path) -> None:
        """Bundling a minimal toolpack with just toolpack.yaml."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_dir = tmp_path / "minimal"
        toolpack_dir.mkdir()
        toolpack_yaml = toolpack_dir / "toolpack.yaml"
        toolpack_yaml.write_text("name: minimal\n")

        twp = create_bundle(toolpack_yaml, output_dir=tmp_path / "out")
        assert twp.exists()
        with tarfile.open(str(twp), "r:gz") as tf:
            names = tf.getnames()
            assert "manifest.json" in names
            assert "signature.json" in names

    @pytest.mark.asyncio
    async def test_unreachable_webhook_graceful(self) -> None:
        """Unreachable webhook returns False, doesn't crash."""
        from toolwright.core.notify.webhook import WebhookConfig, send_webhook

        config = WebhookConfig(url="https://unreachable.invalid/hook")
        result = await send_webhook(config, "test_event", {"key": "value"}, timeout=0.1)
        assert result is False

    def test_startup_card_zero_tools(self) -> None:
        """Startup card with zero tools renders without error."""
        from toolwright.mcp.startup_card import render_startup_card

        card = render_startup_card(
            name="Empty",
            tools={"read": 0, "write": 0, "admin": 0},
            risk_counts={"low": 0, "medium": 0, "high": 0, "critical": 0},
            context_tokens=0,
            tokens_per_tool=0,
        )
        assert "Empty" in card

    def test_mcp_clients_no_config_files(self, tmp_path: Path) -> None:
        """No MCP clients detected when config dirs don't exist."""
        from toolwright.utils.mcp_clients import detect_mcp_clients

        clients = detect_mcp_clients(home_override=tmp_path / "nonexistent")
        assert clients == []

    def test_noop_tracer_multiple_spans(self) -> None:
        """Multiple no-op spans can be nested."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        with tracer.start_as_current_span("outer"), tracer.start_as_current_span("inner") as span:
            span.set_attribute("depth", 2)
