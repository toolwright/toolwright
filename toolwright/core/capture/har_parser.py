"""HAR file parser for importing captured traffic."""

from __future__ import annotations

import contextlib
import fnmatch
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)


class HARParser:
    """Parse HAR files into CaptureSession objects."""

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
        ".js",
        ".ts",
    )

    # Resource types that are typically APIs
    API_RESOURCE_TYPES = ("xhr", "fetch", "other")

    def __init__(self, allowed_hosts: list[str] | None = None) -> None:
        """Initialize parser with allowed hosts.

        Args:
            allowed_hosts: List of allowed host patterns (supports wildcards like *.example.com)
        """
        self.allowed_hosts = allowed_hosts or []
        self.warnings: list[str] = []
        self.stats = {
            "total_entries": 0,
            "imported": 0,
            "filtered_static": 0,
            "filtered_non_api": 0,
            "filtered_host": 0,
        }

    def parse_file(self, path: Path, name: str | None = None) -> CaptureSession:
        """Parse a HAR file into a CaptureSession.

        Args:
            path: Path to HAR file
            name: Optional name for the session

        Returns:
            CaptureSession containing parsed exchanges
        """
        self.warnings = []
        self.stats = {
            "total_entries": 0,
            "imported": 0,
            "filtered_static": 0,
            "filtered_non_api": 0,
            "filtered_host": 0,
        }

        har_data = self._load_har(path)
        if not har_data:
            return CaptureSession(
                name=name,
                source=CaptureSource.HAR,
                source_file=str(path),
                allowed_hosts=self.allowed_hosts,
                warnings=self.warnings,
            )

        exchanges = self._parse_entries(har_data)

        return CaptureSession(
            name=name or path.stem,
            source=CaptureSource.HAR,
            source_file=str(path),
            allowed_hosts=self.allowed_hosts,
            exchanges=exchanges,
            total_requests=self.stats["total_entries"],
            filtered_requests=(
                self.stats["filtered_static"]
                + self.stats["filtered_non_api"]
                + self.stats["filtered_host"]
            ),
            warnings=self.warnings,
        )

    def parse_dict(self, har_data: dict[str, Any], name: str | None = None) -> CaptureSession:
        """Parse a HAR dict into a CaptureSession.

        Args:
            har_data: HAR data as dict
            name: Optional name for the session

        Returns:
            CaptureSession containing parsed exchanges
        """
        self.warnings = []
        self.stats = {
            "total_entries": 0,
            "imported": 0,
            "filtered_static": 0,
            "filtered_non_api": 0,
            "filtered_host": 0,
        }

        exchanges = self._parse_entries(har_data)

        return CaptureSession(
            name=name,
            source=CaptureSource.HAR,
            allowed_hosts=self.allowed_hosts,
            exchanges=exchanges,
            total_requests=self.stats["total_entries"],
            filtered_requests=(
                self.stats["filtered_static"]
                + self.stats["filtered_non_api"]
                + self.stats["filtered_host"]
            ),
            warnings=self.warnings,
        )

    def _load_har(self, path: Path) -> dict[str, Any] | None:
        """Load HAR data from file."""
        if not path.exists():
            self.warnings.append(f"HAR file not found: {path}")
            return None

        try:
            with open(path, encoding="utf-8") as f:
                result: dict[str, Any] = json.load(f)
                return result
        except json.JSONDecodeError as e:
            self.warnings.append(f"Invalid JSON in HAR file: {e}")
            return None
        except Exception as e:
            self.warnings.append(f"Error reading HAR file: {e}")
            return None

    def _parse_entries(self, har_data: dict[str, Any]) -> list[HttpExchange]:
        """Parse HAR entries into HttpExchange objects."""
        entries = har_data.get("log", {}).get("entries", [])
        self.stats["total_entries"] = len(entries)

        exchanges: list[HttpExchange] = []
        for entry in entries:
            exchange = self._parse_entry(entry)
            if exchange:
                exchanges.append(exchange)
                self.stats["imported"] += 1

        return exchanges

    def _parse_entry(self, entry: dict[str, Any]) -> HttpExchange | None:
        """Parse a single HAR entry into an HttpExchange."""
        request = entry.get("request", {})
        response = entry.get("response", {})

        url = request.get("url", "")
        if not url:
            return None

        # Parse URL
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"

        # Check allowed hosts
        if not self._is_allowed_host(host):
            self.stats["filtered_host"] += 1
            return None

        # Filter static files
        path_lower = path.lower()
        if any(path_lower.endswith(ext) for ext in self.STATIC_EXTENSIONS):
            self.stats["filtered_static"] += 1
            return None

        # Get method
        method_str = request.get("method", "GET").upper()

        # Filter CORS preflight requests (OPTIONS produces noise endpoints)
        if method_str == "OPTIONS":
            self.stats["filtered_options"] = self.stats.get("filtered_options", 0) + 1
            return None

        # Get response headers
        response_headers = {
            h["name"].lower(): h["value"] for h in response.get("headers", [])
        }
        content_type = response_headers.get("content-type", "")

        # Filter WebSocket entries (cannot be replayed as MCP tools)
        resource_type = entry.get("_resourceType", "").lower()
        is_websocket = (
            resource_type == "websocket"
            or response_headers.get("upgrade", "").lower() == "websocket"
        )
        if is_websocket:
            self.warnings.append(
                f"WebSocket entry skipped: {url} "
                "-- streaming connections cannot be replayed as MCP tools."
            )
            self.stats["filtered_streaming"] = self.stats.get("filtered_streaming", 0) + 1
            return None

        # Filter SSE entries (cannot be replayed as MCP tools)
        ct_lower = content_type.lower()
        if ct_lower.startswith("text/event-stream"):
            self.warnings.append(
                f"SSE endpoint skipped: {url} "
                "-- Server-Sent Events streams cannot be replayed as MCP tools."
            )
            self.stats["filtered_streaming"] = self.stats.get("filtered_streaming", 0) + 1
            return None

        # Filter non-API responses
        if not self._is_api_request(url, method_str, content_type, entry):
            self.stats["filtered_non_api"] += 1
            return None

        # Parse method
        try:
            method = HTTPMethod(method_str)
        except ValueError:
            method = HTTPMethod.GET

        # Parse headers
        request_headers = {h["name"]: h["value"] for h in request.get("headers", [])}
        resp_headers = {h["name"]: h["value"] for h in response.get("headers", [])}

        # Parse body
        request_body = None
        request_body_json = None
        post_data = request.get("postData", {})
        if post_data:
            request_body = post_data.get("text", "")
            if request_body:
                request_body_json = self._try_parse_json(request_body)

        response_body = None
        response_body_json = None
        content = response.get("content", {})
        if content:
            response_body = content.get("text", "")
            if response_body:
                response_body_json = self._try_parse_json(response_body)

        # Parse timestamp
        timestamp = None
        timestamp_str = entry.get("startedDateTime")
        if timestamp_str:
            with contextlib.suppress(ValueError):
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

        return HttpExchange(
            url=url,
            method=method,
            host=host,
            path=path,
            request_headers=request_headers,
            request_body=request_body,
            request_body_json=request_body_json,
            response_status=response.get("status"),
            response_headers=resp_headers,
            response_body=response_body,
            response_body_json=response_body_json,
            response_content_type=content_type,
            timestamp=timestamp,
            duration_ms=entry.get("time"),
            source=CaptureSource.HAR,
            notes={
                "from_har": True,
                "har_time_ms": entry.get("time", 0),
                "resource_type": entry.get("_resourceType", ""),
            },
        )

    def _is_allowed_host(self, host: str) -> bool:
        """Check if host matches allowed hosts."""
        if not self.allowed_hosts:
            return True

        for pattern in self.allowed_hosts:
            if pattern.startswith("*."):
                # Wildcard subdomain matching
                suffix = pattern[1:]  # .example.com
                if host == pattern[2:] or host.endswith(suffix):
                    return True
            elif fnmatch.fnmatch(host, pattern) or host == pattern:
                return True

        return False

    def _is_api_request(
        self, url: str, method: str, content_type: str, entry: dict[str, Any]
    ) -> bool:
        """Determine if a request looks like an API call."""
        from urllib.parse import urlparse

        from toolwright.core.capture.path_blocklist import is_blocked_path

        path = urlparse(url).path
        if is_blocked_path(path):
            return False

        # Check resource type if available (Chrome DevTools includes this)
        resource_type = entry.get("_resourceType", "").lower()
        if resource_type in self.API_RESOURCE_TYPES:
            return True

        # Check content type
        ct_lower = content_type.lower()
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

        # POST/PUT/PATCH/DELETE are more likely to be API calls
        return method in ("POST", "PUT", "PATCH", "DELETE") and "html" not in ct_lower

    def _try_parse_json(self, text: str) -> dict[str, Any] | list[Any] | None:
        """Try to parse text as a JSON object or array."""
        if not text:
            return None
        try:
            result = json.loads(text)
            if isinstance(result, dict | list):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        return None
