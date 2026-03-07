"""Tests for overlay lifecycle management (crash restart, health monitoring)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStdioLifecycleManager:
    @pytest.mark.asyncio
    async def test_restart_with_backoff_succeeds(self):
        from toolwright.overlay.lifecycle import StdioLifecycleManager

        conn = AsyncMock()
        conn.reconnect = AsyncMock()
        conn.is_connected = True

        manager = StdioLifecycleManager()
        success = await manager.restart_with_backoff(conn, max_attempts=3)
        assert success is True
        conn.reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_retries_on_failure(self):
        from toolwright.overlay.lifecycle import StdioLifecycleManager

        conn = AsyncMock()
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("failed")

        conn.reconnect = fail_then_succeed
        conn.is_connected = True

        manager = StdioLifecycleManager()
        success = await manager.restart_with_backoff(conn, max_attempts=5)
        assert success is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_restart_gives_up_after_max_attempts(self):
        from toolwright.overlay.lifecycle import StdioLifecycleManager

        conn = AsyncMock()
        conn.reconnect = AsyncMock(side_effect=ConnectionError("permanent failure"))

        manager = StdioLifecycleManager()
        success = await manager.restart_with_backoff(conn, max_attempts=2)
        assert success is False


class TestHttpHealthMonitor:
    @pytest.mark.asyncio
    async def test_health_check_calls_list_tools(self):
        from toolwright.overlay.lifecycle import HttpHealthMonitor

        conn = AsyncMock()
        conn.list_tools = AsyncMock(return_value=[])
        conn.is_connected = True

        monitor = HttpHealthMonitor()
        is_healthy = await monitor.check_health(conn)
        assert is_healthy is True
        conn.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_error(self):
        from toolwright.overlay.lifecycle import HttpHealthMonitor

        conn = AsyncMock()
        conn.list_tools = AsyncMock(side_effect=Exception("timeout"))

        monitor = HttpHealthMonitor()
        is_healthy = await monitor.check_health(conn)
        assert is_healthy is False
