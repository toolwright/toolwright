"""OpenAPI discovery: probe hosts for OpenAPI specs at well-known paths.

Given a hostname (or URL), this module tries a series of conventional
paths where OpenAPI/Swagger specs are commonly served. On the first
successful response it parses the spec via the existing OpenAPIParser and
returns a CaptureSession ready for downstream compilation.
"""

from __future__ import annotations

import contextlib
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from toolwright.core.capture.openapi_parser import OpenAPIParser
from toolwright.models.capture import CaptureSession

logger = logging.getLogger(__name__)


class OpenAPIDiscovery:
    """Probes hosts for OpenAPI specs at well-known paths."""

    WELL_KNOWN_PATHS = [
        "/openapi.json",
        "/openapi.yaml",
        "/swagger.json",
        "/v1/openapi.json",
        "/api-docs",
        "/.well-known/openapi.json",
    ]

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover(self, host: str) -> CaptureSession | None:
        """Probe *host* for an OpenAPI spec.

        Returns a ``CaptureSession`` built from the first spec found, or
        ``None`` if no valid spec could be retrieved from any well-known
        path.
        """
        base_url = self._normalise_host(host)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for path in self.WELL_KNOWN_PATHS:
                url = f"{base_url}{path}"
                try:
                    resp = await client.get(url)
                except (httpx.HTTPError, OSError):
                    # Timeout, connection refused, DNS failure, etc.
                    logger.debug("Probe failed for %s", url, exc_info=True)
                    continue

                if resp.status_code != 200:
                    continue

                session = self._try_parse(resp.text, base_url)
                if session is not None:
                    return session

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_host(host: str) -> str:
        """Ensure *host* has a scheme and no trailing slash."""
        host = host.rstrip("/")
        parsed = urlparse(host)
        if not parsed.scheme:
            host = f"https://{host}"
        return host

    @staticmethod
    def _try_parse(spec_text: str, base_url: str) -> CaptureSession | None:
        """Attempt to parse raw spec text into a CaptureSession."""
        # Quick JSON sanity check before writing to disk.
        try:
            json.loads(spec_text)
        except (json.JSONDecodeError, ValueError):
            # Could be YAML -- try anyway, but if both fail we give up.
            import yaml  # noqa: F811

            try:
                yaml.safe_load(spec_text)
            except Exception:
                return None

        # Determine file extension from content heuristic.
        ext = ".json" if spec_text.lstrip().startswith("{") else ".yaml"

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False
            ) as tmp:
                tmp.write(spec_text)
                tmp_path = Path(tmp.name)

            parsed_url = urlparse(base_url)
            host_for_allowlist = parsed_url.netloc or parsed_url.path

            parser = OpenAPIParser(allowed_hosts=[host_for_allowlist])
            session = parser.parse_file(tmp_path)
            return session
        except Exception:
            logger.debug("Failed to parse spec from %s", base_url, exc_info=True)
            return None
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)
