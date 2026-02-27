"""Playwright-based traffic capture for interactive recording sessions.

This module captures HTTP traffic using Playwright's network interception,
allowing users to interact with a browser while recording API traffic.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)


class PlaywrightCapture:
    """Capture HTTP traffic using Playwright browser automation.

    Records network requests/responses during an interactive browser session,
    allowing users to navigate and interact while traffic is captured.
    """

    # Static file extensions to filter out
    STATIC_EXTENSIONS = (
        ".css",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".map",
    )

    # Resource types to filter out
    FILTERED_RESOURCE_TYPES = (
        "stylesheet",
        "image",
        "font",
        "media",
        "manifest",
        "other",
    )

    def __init__(
        self,
        allowed_hosts: list[str],
        headless: bool = False,
        timeout_ms: int = 60000,
        storage_state_path: str | None = None,
        save_storage_state_path: str | None = None,
    ) -> None:
        """Initialize Playwright capture.

        Args:
            allowed_hosts: List of allowed host patterns (required)
            headless: Run browser in headless mode (default: False for interactive)
            timeout_ms: Default timeout for navigation in milliseconds
            storage_state_path: Path to load browser storage state (cookies, localStorage)
            save_storage_state_path: Path to save browser storage state after capture
        """
        if not allowed_hosts:
            raise ValueError("At least one allowed host is required")

        self.allowed_hosts = allowed_hosts
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.storage_state_path = storage_state_path
        self.save_storage_state_path = save_storage_state_path

        self._exchanges: list[HttpExchange] = []
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._pending_tasks: list[asyncio.Task[None]] = []
        self._stop_requested = False

        self.stats = {
            "total_requests": 0,
            "captured": 0,
            "filtered_static": 0,
            "filtered_host": 0,
            "filtered_resource_type": 0,
        }

    async def capture(
        self,
        start_url: str,
        name: str | None = None,
        duration_seconds: int | None = None,
        script_path: str | None = None,
        settle_delay_seconds: float = 0.0,
    ) -> CaptureSession:
        """Start a capture session.

        Args:
            start_url: URL to navigate to initially
            name: Optional name for the capture session
            duration_seconds: Optional capture duration for non-interactive runs
            script_path: Optional Python file exposing async run(page, context)
            settle_delay_seconds: Optional post-script settling delay in seconds

        Returns:
            CaptureSession containing captured exchanges
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ImportError(
                "Playwright is required for capture record mode. "
                "Install with: pip install 'toolwright[playwright]'"
            ) from e

        self._exchanges = []
        self._pending_requests = {}
        self._pending_tasks = []
        self._stop_requested = False
        self.stats = {
            "total_requests": 0,
            "captured": 0,
            "filtered_static": 0,
            "filtered_host": 0,
            "filtered_resource_type": 0,
        }

        # Set up signal handler for graceful shutdown
        original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._signal_handler)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                ctx_kwargs: dict[str, Any] = {}
                if self.storage_state_path:
                    ctx_kwargs["storage_state"] = self.storage_state_path
                context = await browser.new_context(**ctx_kwargs)
                page = await context.new_page()

                # Set up network interception
                page.on("request", self._on_request)
                page.on("response", self._on_response)
                page.on("requestfailed", self._on_request_failed)

                # Navigate to starting URL
                print(f"\nNavigating to: {start_url}")
                await page.goto(start_url, timeout=self.timeout_ms)

                if script_path:
                    print(f"Running scripted capture: {script_path}")
                    script_runner = self._load_script_runner(script_path)
                    await script_runner(page, context)
                    if settle_delay_seconds > 0:
                        await asyncio.sleep(settle_delay_seconds)
                elif duration_seconds is not None:
                    print(f"Recording for {duration_seconds}s...")
                    await asyncio.sleep(duration_seconds)
                else:
                    # Wait for user interaction
                    print("\n" + "=" * 60)
                    print("RECORDING - Interact with the browser")
                    print("Press Ctrl+C to stop recording")
                    print("=" * 60 + "\n")

                    # Keep running until stop is requested
                    while not self._stop_requested:
                        await asyncio.sleep(0.5)
                        if page.is_closed():
                            break

                print("\nStopping capture...")
                # Wait for all in-flight exchange creation tasks to complete
                if self._pending_tasks:
                    await asyncio.gather(*self._pending_tasks, return_exceptions=True)
                    self._pending_tasks.clear()
                if self.save_storage_state_path:
                    await context.storage_state(path=self.save_storage_state_path)
                await browser.close()

        finally:
            # Restore original signal handler
            signal.signal(signal.SIGINT, original_sigint)

        return CaptureSession(
            name=name or self._generate_name(start_url),
            source=CaptureSource.PLAYWRIGHT,
            allowed_hosts=self.allowed_hosts,
            exchanges=self._exchanges,
            total_requests=self.stats["total_requests"],
            filtered_requests=(
                self.stats["filtered_static"]
                + self.stats["filtered_host"]
                + self.stats["filtered_resource_type"]
            ),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        """Handle Ctrl+C to stop recording gracefully."""
        self._stop_requested = True
        # Print on a new line to not break the terminal output
        print("\n\nReceived stop signal, finishing up...")

    def _on_request(self, request: Any) -> None:
        """Handle request start event."""
        self.stats["total_requests"] += 1

        url = request.url
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"

        # Filter by allowed hosts
        if not self._is_allowed_host(host):
            self.stats["filtered_host"] += 1
            return

        # Filter static resources
        if path.lower().endswith(self.STATIC_EXTENSIONS):
            self.stats["filtered_static"] += 1
            return

        # Filter by resource type
        resource_type = request.resource_type
        if resource_type in self.FILTERED_RESOURCE_TYPES:
            self.stats["filtered_resource_type"] += 1
            return

        # Store pending request
        request_id = self._get_request_id(request)
        self._pending_requests[request_id] = {
            "url": url,
            "method": request.method,
            "host": host,
            "path": path,
            "headers": dict(request.headers),
            "post_data": None,
            "timestamp": datetime.now(UTC),
        }

        # Get post data if available
        with contextlib.suppress(Exception):
            post_data = request.post_data
            if post_data:
                self._pending_requests[request_id]["post_data"] = post_data

    def _on_response(self, response: Any) -> None:
        """Handle response event."""
        request = response.request
        request_id = self._get_request_id(request)

        # Check if we have a pending request
        pending = self._pending_requests.pop(request_id, None)
        if not pending:
            return

        # Create exchange
        task = asyncio.create_task(self._create_exchange(pending, response))
        self._pending_tasks.append(task)

    def _on_request_failed(self, request: Any) -> None:
        """Handle failed request event."""
        request_id = self._get_request_id(request)
        self._pending_requests.pop(request_id, None)

    async def _create_exchange(
        self,
        pending: dict[str, Any],
        response: Any,
    ) -> None:
        """Create HttpExchange from pending request and response."""
        # Get response body
        response_body: str | None = None
        response_body_json: dict[str, Any] | list[Any] | None = None

        with contextlib.suppress(Exception):
            response_body = await response.text()
            if response_body:
                with contextlib.suppress(json.JSONDecodeError):
                    parsed = json.loads(response_body)
                    if isinstance(parsed, dict | list):
                        response_body_json = parsed

        # Parse request body
        request_body = pending.get("post_data")
        request_body_json: dict[str, Any] | list[Any] | None = None
        if request_body:
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(request_body)
                if isinstance(parsed, dict | list):
                    request_body_json = parsed

        # Get method
        method_str = pending["method"].upper()
        try:
            method = HTTPMethod(method_str)
        except ValueError:
            method = HTTPMethod.GET

        # Get content type
        response_headers = {}
        with contextlib.suppress(Exception):
            response_headers = dict(response.headers)
        content_type = response_headers.get("content-type", "")

        # Filter non-API responses after we have the content type
        if not self._is_api_response(pending["url"], method_str, content_type):
            return

        exchange = HttpExchange(
            url=pending["url"],
            method=method,
            host=pending["host"],
            path=pending["path"],
            request_headers=pending["headers"],
            request_body=request_body,
            request_body_json=request_body_json,
            response_status=response.status,
            response_headers=response_headers,
            response_body=response_body,
            response_body_json=response_body_json,
            response_content_type=content_type,
            timestamp=pending["timestamp"],
            source=CaptureSource.PLAYWRIGHT,
            notes={
                "from_playwright": True,
                "resource_type": response.request.resource_type,
            },
        )

        self._exchanges.append(exchange)
        self.stats["captured"] += 1

        # Print progress
        status_emoji = "✓" if 200 <= response.status < 300 else "✗"
        print(f"  {status_emoji} {method_str} {pending['path'][:50]} [{response.status}]")

    def _get_request_id(self, request: Any) -> str:
        """Generate a unique ID for a request."""
        # Use Playwright's internal ID if available, fallback to URL + method
        return f"{request.url}::{request.method}::{id(request)}"

    def _is_allowed_host(self, host: str) -> bool:
        """Check if host matches allowed hosts."""
        import fnmatch

        for pattern in self.allowed_hosts:
            if pattern.startswith("*."):
                suffix = pattern[1:]  # .example.com
                if host == pattern[2:] or host.endswith(suffix):
                    return True
            elif fnmatch.fnmatch(host, pattern) or host == pattern:
                return True

        return False

    def _is_api_response(self, url: str, method: str, content_type: str) -> bool:
        """Check if response looks like an API response."""
        from urllib.parse import urlparse

        from toolwright.core.capture.path_blocklist import is_blocked_path

        path = urlparse(url).path
        if is_blocked_path(path):
            return False

        ct_lower = content_type.lower()

        # JSON/XML/GraphQL responses are APIs
        if any(api_type in ct_lower for api_type in ("json", "xml", "graphql", "protobuf")):
            return True

        # Check URL patterns
        url_lower = url.lower()
        api_patterns = [
            "/api/",
            "/v1/",
            "/v2/",
            "/v3/",
            "/graphql",
            "/rest/",
            "/services/",
            ".json",
            "/query",
            "/mutation",
        ]
        if any(pattern in url_lower for pattern in api_patterns):
            return True

        # Non-GET methods that aren't HTML are likely APIs
        return method in ("POST", "PUT", "PATCH", "DELETE") and "html" not in ct_lower

    def _generate_name(self, url: str) -> str:
        """Generate a session name from the start URL."""
        parsed = urlparse(url)
        host = parsed.netloc.replace(".", "_").replace(":", "_")
        date = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"playwright_{host}_{date}"

    def _load_script_runner(self, script_path: str) -> Callable[[Any, Any], Awaitable[None]]:
        """Load a scripted capture runner from a Python file."""
        path = Path(script_path)
        if not path.exists():
            raise FileNotFoundError(f"Capture script not found: {script_path}")

        spec = importlib.util.spec_from_file_location("toolwright_capture_script", path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Unable to load capture script: {script_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        run_fn = getattr(module, "run", None)
        if run_fn is None or not callable(run_fn):
            raise ValueError("Capture script must define async function run(page, context)")
        if not asyncio.iscoroutinefunction(run_fn):
            raise TypeError("Capture script run(page, context) must be async")

        return cast(Callable[[Any, Any], Awaitable[None]], run_fn)


def run_capture(
    start_url: str,
    allowed_hosts: list[str],
    name: str | None = None,
    headless: bool = False,
) -> CaptureSession:
    """Convenience function to run a Playwright capture.

    Args:
        start_url: URL to navigate to initially
        allowed_hosts: List of allowed host patterns
        name: Optional session name
        headless: Run in headless mode

    Returns:
        CaptureSession with captured traffic
    """
    capture = PlaywrightCapture(allowed_hosts=allowed_hosts, headless=headless)
    return asyncio.run(capture.capture(start_url=start_url, name=name))


# Entry point for synchronous usage
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m toolwright.core.capture.playwright_capture <url> <allowed_host>")
        sys.exit(1)

    url = sys.argv[1]
    hosts = sys.argv[2:]
    session = run_capture(url, hosts)
    print(f"\nCaptured {len(session.exchanges)} exchanges")
