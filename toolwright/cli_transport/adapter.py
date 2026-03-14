"""CLI transport adapter — governed tool execution via JSONL on stdin/stdout.

Protocol:
  - Input (stdin, one JSON object per line):
      {"tool": "get_users", "args": {"limit": 10}}
      {"method": "list_tools"}
  - Output (stdout, one JSON object per line):
      {"ok": true, "result": {...}}
      {"ok": false, "error": "..."}

Special methods:
  - list_tools: returns the available tool definitions
  - exit/quit: graceful shutdown

Security:
  - All tool calls go through GovernanceRuntime (same lockfile, policy,
    rules, circuit breakers as MCP transport)
  - subprocess execution uses shell=False, stdin=DEVNULL
  - CLI tool paths validated against approved manifest
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from toolwright.core.governance.engine import PipelineResult
from toolwright.core.governance.runtime import GovernanceRuntime

logger = logging.getLogger(__name__)


class CLITransportAdapter:
    """Governed tool execution via JSONL on stdin/stdout.

    Usage:
        adapter = CLITransportAdapter(runtime)
        adapter.run()  # blocks, reads stdin, writes stdout
    """

    def __init__(self, runtime: GovernanceRuntime) -> None:
        self.runtime = runtime

    def run(self) -> None:
        """Run the JSONL read-eval-print loop (blocking)."""
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """Async main loop: read JSONL from stdin, process, write JSONL to stdout."""
        loop = asyncio.get_event_loop()

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write_response(
                    {"ok": False, "error": f"Invalid JSON: {exc}"}
                )
                continue

            if not isinstance(request, dict):
                self._write_response(
                    {"ok": False, "error": "Request must be a JSON object"}
                )
                continue

            response = await self._handle_request(request)
            self._write_response(response)

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Route a request to the appropriate handler."""
        # Special methods
        method = request.get("method")
        if method == "list_tools":
            return self._handle_list_tools()
        if method in ("exit", "quit"):
            return {"ok": True, "result": "bye"}

        # Tool invocation
        tool_name = request.get("tool")
        if not tool_name:
            return {
                "ok": False,
                "error": 'Missing "tool" field. Use {"tool": "name", "args": {...}}',
            }

        args = request.get("args") or {}
        if not isinstance(args, dict):
            return {"ok": False, "error": '"args" must be a JSON object'}

        return await self._handle_tool_call(tool_name, args)

    def _handle_list_tools(self) -> dict[str, Any]:
        """Return available tool definitions."""
        tools = []
        for action in self.runtime.actions.values():
            tools.append(
                {
                    "name": action["name"],
                    "description": action.get("description", ""),
                    "input_schema": action.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                }
            )
        return {"ok": True, "result": {"tools": tools}}

    async def _handle_tool_call(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool call through the governance pipeline."""
        try:
            result: PipelineResult = await self.runtime.engine.execute(
                tool_name,
                args,
                toolset_name=self.runtime.toolset_name,
            )
        except Exception as exc:
            logger.error(
                "Unhandled error in CLI tool call '%s': %s",
                tool_name,
                exc,
                exc_info=True,
            )
            return {
                "ok": False,
                "error": f"Internal error: {type(exc).__name__}: {exc}",
            }

        if result.is_error:
            payload = result.payload
            if isinstance(payload, dict):
                return {"ok": False, "error": payload}
            return {"ok": False, "error": str(payload)}

        return {"ok": True, "result": result.payload}

    @staticmethod
    def _write_response(response: dict[str, Any]) -> None:
        """Write a single JSONL response to stdout."""
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def run_cli_transport(
    runtime: GovernanceRuntime,
) -> None:
    """Entry point for CLI transport — called by `toolwright serve --transport cli`."""
    adapter = CLITransportAdapter(runtime)
    adapter.run()
