"""Performance benchmarks for the CORRECT and KILL pillars.

Target: Rule evaluation < 5ms with 50 rules and 100 history entries.
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.core.kill.breaker import CircuitBreakerRegistry
from toolwright.models.rule import (
    BehavioralRule,
    PrerequisiteConfig,
    ProhibitionConfig,
    ParameterConfig,
    RuleKind,
    SessionRateConfig,
)


@pytest.fixture
def populated_engine(tmp_path: Path) -> tuple[RuleEngine, SessionHistory]:
    """Create a rule engine with 50 rules and a session with 100 entries."""
    rules_path = tmp_path / "rules.json"
    engine = RuleEngine(rules_path)

    # Add 50 rules of mixed types
    for i in range(20):
        engine.add_rule(BehavioralRule(
            rule_id=f"prereq-{i}",
            kind=RuleKind.PREREQUISITE,
            description=f"Prerequisite rule {i}",
            target_tool_ids=[f"tool_{i}"],
            config=PrerequisiteConfig(required_tool_ids=[f"dep_{i}"]),
        ))

    for i in range(10):
        engine.add_rule(BehavioralRule(
            rule_id=f"prohib-{i}",
            kind=RuleKind.PROHIBITION,
            description=f"Prohibition rule {i}",
            target_tool_ids=[f"blocked_{i}"],
            config=ProhibitionConfig(always=True),
        ))

    for i in range(10):
        engine.add_rule(BehavioralRule(
            rule_id=f"param-{i}",
            kind=RuleKind.PARAMETER,
            description=f"Parameter rule {i}",
            target_tool_ids=[f"param_tool_{i}"],
            config=ParameterConfig(
                param_name="role",
                allowed_values=["user", "admin"],
            ),
        ))

    for i in range(10):
        engine.add_rule(BehavioralRule(
            rule_id=f"rate-{i}",
            kind=RuleKind.RATE,
            description=f"Rate rule {i}",
            target_tool_ids=[f"rate_tool_{i}"],
            config=SessionRateConfig(max_calls=100),
        ))

    assert len(engine.list_rules()) == 50

    # Create session with 100 entries
    session = SessionHistory()
    for i in range(100):
        session.record(
            f"tool_{i % 20}",
            "GET",
            "api.example.com",
            {"id": str(i)},
            f"result_{i}",
        )

    assert session.call_count() == 100

    return engine, session


class TestRuleEvaluationPerformance:
    """Rule evaluation should be fast even with many rules and history."""

    def test_evaluation_under_5ms(self, populated_engine):
        """Single evaluate() call should take < 5ms."""
        engine, session = populated_engine

        # Warm up
        engine.evaluate("tool_0", "GET", "api.example.com", {}, session)

        # Benchmark
        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            engine.evaluate("tool_0", "GET", "api.example.com", {}, session)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 5.0, f"Average evaluation time {avg_ms:.2f}ms exceeds 5ms target"

    def test_evaluation_with_matching_rule(self, populated_engine):
        """Evaluation against a matching prerequisite rule should be fast."""
        engine, session = populated_engine

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            # tool_5 has a prerequisite on dep_5
            engine.evaluate("tool_5", "PUT", "api.example.com", {}, session)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 5.0, f"Average evaluation time {avg_ms:.2f}ms exceeds 5ms target"

    def test_list_rules_performance(self, populated_engine):
        """Listing 50 rules should be fast."""
        engine, _ = populated_engine

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            rules = engine.list_rules()
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, f"Average list_rules time {avg_ms:.2f}ms exceeds 1ms target"
        assert len(rules) == 50


class TestCircuitBreakerPerformance:
    """Circuit breaker operations should be fast."""

    def test_should_allow_performance(self, tmp_path: Path):
        """should_allow() lookup should be fast."""
        registry = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")

        # Pre-populate with 50 breakers
        for i in range(50):
            registry.should_allow(f"tool_{i}")

        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            registry.should_allow("tool_25")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, f"Average should_allow time {avg_ms:.2f}ms exceeds 1ms target"

    def test_quarantine_report_performance(self, tmp_path: Path):
        """quarantine_report() scan should be fast."""
        registry = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")

        # Pre-populate with 50 breakers, 10 killed
        for i in range(50):
            registry.should_allow(f"tool_{i}")
        for i in range(10):
            registry.kill_tool(f"tool_{i}", "test")

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            report = registry.quarantine_report()
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, f"Average quarantine_report time {avg_ms:.2f}ms exceeds 1ms target"
        assert len(report) == 10
