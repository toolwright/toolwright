"""Tests for session history tracker."""

from __future__ import annotations

from toolwright.core.correct.session import SessionHistory


class TestSessionHistory:
    def test_record_and_has_called(self) -> None:
        h = SessionHistory()
        assert h.has_called("get_user") is False
        h.record("get_user", "GET", "api.example.com", {}, "ok")
        assert h.has_called("get_user") is True

    def test_has_called_with_args(self) -> None:
        h = SessionHistory()
        h.record("get_user", "GET", "api.example.com", {"id": "123"}, "ok")
        assert h.has_called("get_user", with_args={"id": "123"}) is True
        assert h.has_called("get_user", with_args={"id": "456"}) is False

    def test_call_count(self) -> None:
        h = SessionHistory()
        h.record("list_items", "GET", "api.example.com", {}, "ok")
        h.record("list_items", "GET", "api.example.com", {}, "ok")
        h.record("get_item", "GET", "api.example.com", {}, "ok")
        assert h.call_count("list_items") == 2
        assert h.call_count("get_item") == 1
        assert h.call_count() == 3

    def test_last_call(self) -> None:
        h = SessionHistory()
        h.record("a", "GET", "h", {}, "ok")
        h.record("b", "POST", "h", {"x": 1}, "ok")
        last = h.last_call()
        assert last is not None
        assert last.tool_id == "b"

    def test_last_call_specific_tool(self) -> None:
        h = SessionHistory()
        h.record("a", "GET", "h", {}, "r1")
        h.record("b", "POST", "h", {}, "r2")
        h.record("a", "GET", "h", {"v": 2}, "r3")
        last_a = h.last_call("a")
        assert last_a is not None
        assert last_a.result_summary == "r3"

    def test_last_call_empty(self) -> None:
        h = SessionHistory()
        assert h.last_call() is None

    def test_clear(self) -> None:
        h = SessionHistory()
        h.record("a", "GET", "h", {}, "ok")
        h.clear()
        assert h.call_count() == 0
        assert h.has_called("a") is False

    def test_max_history_trims(self) -> None:
        h = SessionHistory(max_history=5)
        for i in range(10):
            h.record(f"tool_{i}", "GET", "h", {}, "ok")
        assert h.call_count() == 5
        # Oldest entries should be trimmed
        assert h.has_called("tool_0") is False
        assert h.has_called("tool_9") is True

    def test_calls_since(self) -> None:
        h = SessionHistory()
        h.record("a", "GET", "h", {}, "ok")
        # All calls within the last 10 seconds
        recent = h.calls_since(10)
        assert len(recent) == 1
        assert recent[0].tool_id == "a"

    def test_call_sequence(self) -> None:
        h = SessionHistory()
        h.record("a", "GET", "h", {}, "ok")
        h.record("b", "GET", "h", {}, "ok")
        h.record("c", "GET", "h", {}, "ok")
        seq = h.call_sequence()
        assert seq == ["a", "b", "c"]
