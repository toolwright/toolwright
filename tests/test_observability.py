"""Tests for observability: tracing and metrics (Sprint 7)."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class TestTracer:
    """OTEL-style tracing with no-op fallback."""

    def test_create_tracer_without_otel(self) -> None:
        """When opentelemetry is not installed, get a no-op tracer."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        assert tracer is not None

    def test_noop_tracer_span_is_context_manager(self) -> None:
        """No-op tracer spans should work as context managers."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        with tracer.start_as_current_span("test-op") as span:
            assert span is not None

    def test_noop_span_set_attribute(self) -> None:
        """No-op spans should accept set_attribute without error."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        with tracer.start_as_current_span("test-op") as span:
            span.set_attribute("key", "value")

    def test_noop_span_record_exception(self) -> None:
        """No-op spans should accept record_exception without error."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        with tracer.start_as_current_span("test-op") as span:
            span.record_exception(RuntimeError("test"))

    def test_noop_span_set_status(self) -> None:
        """No-op spans should accept set_status without error."""
        from toolwright.mcp.observe import create_tracer

        tracer = create_tracer("test")
        with tracer.start_as_current_span("test-op") as span:
            span.set_status("ERROR", "something failed")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    """Prometheus-style metrics with hand-rolled fallback."""

    def test_create_metrics_registry(self) -> None:
        """Should create a metrics registry."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        assert registry is not None

    def test_counter_increment(self) -> None:
        """Counter should increment."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        registry.increment("tool_calls_total", labels={"tool": "get_user"})
        registry.increment("tool_calls_total", labels={"tool": "get_user"})
        assert registry.get("tool_calls_total", labels={"tool": "get_user"}) == 2

    def test_counter_different_labels(self) -> None:
        """Counters with different labels should be independent."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        registry.increment("tool_calls_total", labels={"tool": "get_user"})
        registry.increment("tool_calls_total", labels={"tool": "list_users"})
        assert registry.get("tool_calls_total", labels={"tool": "get_user"}) == 1
        assert registry.get("tool_calls_total", labels={"tool": "list_users"}) == 1

    def test_gauge_set(self) -> None:
        """Gauge should support set."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        registry.set_gauge("active_connections", 5)
        assert registry.get("active_connections") == 5

    def test_render_prometheus_text(self) -> None:
        """Should render Prometheus text exposition format."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        registry.increment("tool_calls_total", labels={"tool": "get_user"})
        registry.increment("tool_calls_total", labels={"tool": "get_user"})
        registry.set_gauge("active_tools", 12)

        text = registry.render_prometheus()
        assert "tool_calls_total" in text
        assert "active_tools" in text
        assert "12" in text

    def test_unset_counter_returns_zero(self) -> None:
        """Getting an unset counter should return 0."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        assert registry.get("nonexistent") == 0

    def test_histogram_observe(self) -> None:
        """Histogram should accept observations."""
        from toolwright.mcp.observe import MetricsRegistry

        registry = MetricsRegistry()
        registry.observe("request_duration_seconds", 0.5)
        registry.observe("request_duration_seconds", 1.2)
        text = registry.render_prometheus()
        assert "request_duration_seconds" in text
