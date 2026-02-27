#!/usr/bin/env python3
"""Smoke-test an MCP server over stdio, exercising outputSchema validation.

This is intentionally minimal and meant for debugging "outputSchema defined but no
structured output returned" failures in MCP clients.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test an MCP server over stdio.")
    parser.add_argument("--command", required=True, help="Server executable to spawn")
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argument to pass to the server process (repeatable)",
    )
    parser.add_argument(
        "--args-json",
        default=None,
        help="JSON array of args to pass to the server (preferred for flags like --root)",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory for the server process (optional)",
    )
    parser.add_argument(
        "--calls-json",
        default="[]",
        help=(
            "JSON array of calls, e.g. "
            """[{"name":"get_products","arguments":{"limit":2}}]"""
        ),
    )
    parser.add_argument(
        "--print-tools",
        action="store_true",
        help="Print the server tool list and whether outputSchema is advertised",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=4000,
        help="Max chars to print per tool call result (default: 4000)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout seconds for initialize/list/call (default: 30)",
    )
    return parser.parse_args(argv)


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


async def _run_smoke(ns: argparse.Namespace) -> int:
    calls: list[dict[str, Any]] = json.loads(ns.calls_json)
    if not isinstance(calls, list):
        raise ValueError("--calls-json must be a JSON array")

    server_args = list(ns.arg or [])
    if ns.args_json is not None:
        parsed = json.loads(ns.args_json)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("--args-json must be a JSON array of strings")
        server_args = parsed

    server = StdioServerParameters(
        command=ns.command,
        args=server_args,
        cwd=ns.cwd,
    )

    print("spawning server...", flush=True)
    async with stdio_client(server) as (read_stream, write_stream), ClientSession(
        read_stream, write_stream
    ) as session:
        with anyio.fail_after(ns.timeout_seconds):
            await session.initialize()
        print("initialized", flush=True)

        if ns.print_tools:
            with anyio.fail_after(ns.timeout_seconds):
                tools = await session.list_tools()
            print(f"tools={len(tools.tools)}")
            for tool in tools.tools:
                advertised = "yes" if tool.outputSchema else "no"
                print(f"- {tool.name} outputSchema={advertised}")
            sys.stdout.flush()

        for call in calls:
            if not isinstance(call, dict) or "name" not in call:
                raise ValueError("Each call must be an object with at least a 'name' field")
            name = str(call["name"])
            arguments = call.get("arguments")
            if arguments is not None and not isinstance(arguments, dict):
                raise ValueError(f"Call arguments must be an object for tool {name}")

            print(f"\ncall {name}", flush=True)
            with anyio.fail_after(ns.timeout_seconds):
                result = await session.call_tool(name, arguments=arguments or {})

            if result.isError:
                text = ""
                if result.content:
                    text = getattr(result.content[0], "text", "") or ""
                print("isError=true", flush=True)
                print(_truncate(text, ns.max_chars))
                continue

            if result.structuredContent is not None:
                payload = json.dumps(
                    result.structuredContent,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=True,
                )
                print("structured=true", flush=True)
                print(_truncate(payload, ns.max_chars))
                continue

            text = ""
            if result.content:
                text = getattr(result.content[0], "text", "") or ""
            print("structured=false", flush=True)
            print(_truncate(text, ns.max_chars))

    return 0


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    try:
        return anyio.run(_run_smoke, ns)
    except Exception as exc:
        import traceback

        sys.stderr.write(f"mcp_smoke failed: {exc}\n")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
