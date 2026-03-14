"""Observability: tracing and metrics for Toolwright.

Provides a no-op tracer when OpenTelemetry is not installed, and a simple
metrics registry that renders Prometheus text exposition format without
requiring prometheus-client.
"""

from __future__ import annotations

import importlib
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

# ---------------------------------------------------------------------------
# Tracing — No-op fallback when OpenTelemetry is not installed
# ---------------------------------------------------------------------------


class _NoopSpan:
    """Minimal span that accepts OTEL-like calls without doing anything."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exception: BaseException) -> None:  # noqa: ARG002
        pass

    def set_status(self, status: str, description: str = "") -> None:  # noqa: ARG002
        pass


class _NoopTracer:
    """Tracer that produces no-op spans."""

    @contextmanager
    def start_as_current_span(  # noqa: ARG002
        self,
        _name: str,
        **_kwargs: Any,
    ) -> Generator[_NoopSpan, None, None]:
        yield _NoopSpan()


def create_tracer(name: str) -> Any:
    """Create a tracer. Returns OTEL tracer if available, else no-op."""
    try:
        trace_module = importlib.import_module("opentelemetry.trace")
        return trace_module.get_tracer(name)
    except (ImportError, AttributeError):
        return _NoopTracer()


# ---------------------------------------------------------------------------
# Metrics — Hand-rolled Prometheus text format
# ---------------------------------------------------------------------------


class MetricsRegistry:
    """Simple metrics registry with Prometheus text exposition output."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    @staticmethod
    def _label_key(name: str, labels: dict[str, str] | None = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def increment(
        self, name: str, *, labels: dict[str, str] | None = None, amount: float = 1
    ) -> None:
        key = self._label_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + amount

    def set_gauge(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        key = self._label_key(name, labels)
        self._gauges[key] = value

    def observe(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        key = self._label_key(name, labels)
        self._histograms.setdefault(key, []).append(value)

    def get(
        self, name: str, *, labels: dict[str, str] | None = None
    ) -> float:
        key = self._label_key(name, labels)
        if key in self._counters:
            return self._counters[key]
        if key in self._gauges:
            return self._gauges[key]
        return 0

    def render_prometheus(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines: list[str] = []
        for key, value in sorted(self._counters.items()):
            lines.append(f"{key} {value}")
        for key, value in sorted(self._gauges.items()):
            lines.append(f"{key} {value}")
        for key, values in sorted(self._histograms.items()):
            count = len(values)
            total = sum(values)
            lines.append(f"{key}_count {count}")
            lines.append(f"{key}_sum {total}")
        return "\n".join(lines) + "\n" if lines else ""
