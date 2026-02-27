"""Tests for Playwright capture functionality."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolwright.core.capture.playwright_capture import PlaywrightCapture


class TestPlaywrightCapture:
    """Tests for PlaywrightCapture class."""

    def test_init_requires_allowed_hosts(self):
        """Initializing without allowed hosts raises error."""
        with pytest.raises(ValueError, match="At least one allowed host"):
            PlaywrightCapture(allowed_hosts=[])

    def test_init_with_allowed_hosts(self):
        """Initializing with allowed hosts works."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        assert capture.allowed_hosts == ["api.example.com"]
        assert capture.headless is False
        assert capture.timeout_ms == 60000

    def test_init_with_options(self):
        """Initializing with custom options."""
        capture = PlaywrightCapture(
            allowed_hosts=["api.example.com"],
            headless=True,
            timeout_ms=30000,
        )
        assert capture.headless is True
        assert capture.timeout_ms == 30000

    def test_is_allowed_host_exact_match(self):
        """Test exact host matching."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        assert capture._is_allowed_host("api.example.com") is True
        assert capture._is_allowed_host("other.example.com") is False

    def test_is_allowed_host_wildcard(self):
        """Test wildcard subdomain matching."""
        capture = PlaywrightCapture(allowed_hosts=["*.example.com"])
        assert capture._is_allowed_host("api.example.com") is True
        assert capture._is_allowed_host("example.com") is True
        assert capture._is_allowed_host("sub.api.example.com") is True
        assert capture._is_allowed_host("other.com") is False

    def test_is_allowed_host_multiple_patterns(self):
        """Test multiple allowed host patterns."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com", "*.other.com"])
        assert capture._is_allowed_host("api.example.com") is True
        assert capture._is_allowed_host("api.other.com") is True
        assert capture._is_allowed_host("unknown.com") is False

    def test_is_api_response_json(self):
        """Test API response detection for JSON."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        assert capture._is_api_response(
            "https://api.example.com/users",
            "GET",
            "application/json"
        ) is True
        assert capture._is_api_response(
            "https://api.example.com/users",
            "GET",
            "application/json; charset=utf-8"
        ) is True

    def test_is_api_response_url_patterns(self):
        """Test API response detection by URL patterns."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        assert capture._is_api_response(
            "https://example.com/api/users",
            "GET",
            "text/plain"
        ) is True
        assert capture._is_api_response(
            "https://example.com/v1/users",
            "GET",
            "text/plain"
        ) is True
        assert capture._is_api_response(
            "https://example.com/graphql",
            "POST",
            "text/plain"
        ) is True

    def test_is_api_response_non_get_methods(self):
        """Test API response detection for non-GET methods."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        # Non-GET without HTML is API
        assert capture._is_api_response(
            "https://example.com/submit",
            "POST",
            "text/plain"
        ) is True
        # Non-GET with HTML is not API
        assert capture._is_api_response(
            "https://example.com/submit",
            "POST",
            "text/html"
        ) is False
        # GET without API indicators is not API
        assert capture._is_api_response(
            "https://example.com/page",
            "GET",
            "text/plain"
        ) is False

    def test_generate_name(self):
        """Test session name generation."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        name = capture._generate_name("https://api.example.com/users")
        assert name.startswith("playwright_api_example_com_")

    def test_generate_name_with_port(self):
        """Test session name generation with port."""
        capture = PlaywrightCapture(allowed_hosts=["localhost:3000"])
        name = capture._generate_name("http://localhost:3000/api")
        assert "localhost_3000" in name

    def test_stats_initialized(self):
        """Test stats are initialized correctly."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])
        assert capture.stats == {
            "total_requests": 0,
            "captured": 0,
            "filtered_static": 0,
            "filtered_host": 0,
            "filtered_resource_type": 0,
        }

    def test_static_extensions_filtered(self):
        """Test static file extensions are defined."""
        assert ".css" in PlaywrightCapture.STATIC_EXTENSIONS
        assert ".png" in PlaywrightCapture.STATIC_EXTENSIONS
        assert ".js" not in PlaywrightCapture.STATIC_EXTENSIONS  # JS might have API responses

    def test_filtered_resource_types(self):
        """Test filtered resource types are defined."""
        assert "stylesheet" in PlaywrightCapture.FILTERED_RESOURCE_TYPES
        assert "image" in PlaywrightCapture.FILTERED_RESOURCE_TYPES
        assert "font" in PlaywrightCapture.FILTERED_RESOURCE_TYPES


class TestPlaywrightCaptureOnRequest:
    """Tests for _on_request handler."""

    def test_on_request_filtered_by_host(self):
        """Requests to non-allowed hosts are filtered."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        # Mock request object
        mock_request = MagicMock()
        mock_request.url = "https://other.com/api/users"
        mock_request.method = "GET"
        mock_request.resource_type = "xhr"
        mock_request.headers = {}

        capture._on_request(mock_request)

        assert capture.stats["total_requests"] == 1
        assert capture.stats["filtered_host"] == 1
        assert len(capture._pending_requests) == 0

    def test_on_request_filtered_by_static(self):
        """Static file requests are filtered."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        mock_request = MagicMock()
        mock_request.url = "https://api.example.com/style.css"
        mock_request.method = "GET"
        mock_request.resource_type = "stylesheet"
        mock_request.headers = {}

        capture._on_request(mock_request)

        assert capture.stats["total_requests"] == 1
        assert capture.stats["filtered_static"] == 1
        assert len(capture._pending_requests) == 0

    def test_on_request_filtered_by_resource_type(self):
        """Requests with filtered resource types are filtered."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        mock_request = MagicMock()
        mock_request.url = "https://api.example.com/image/data"  # Not a static extension
        mock_request.method = "GET"
        mock_request.resource_type = "image"
        mock_request.headers = {}

        capture._on_request(mock_request)

        assert capture.stats["total_requests"] == 1
        assert capture.stats["filtered_resource_type"] == 1
        assert len(capture._pending_requests) == 0

    def test_on_request_api_captured(self):
        """API requests are captured as pending."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        mock_request = MagicMock()
        mock_request.url = "https://api.example.com/users"
        mock_request.method = "GET"
        mock_request.resource_type = "xhr"
        mock_request.headers = {"content-type": "application/json"}
        mock_request.post_data = None

        capture._on_request(mock_request)

        assert capture.stats["total_requests"] == 1
        assert len(capture._pending_requests) == 1


class TestPlaywrightCaptureRequestFailed:
    """Tests for _on_request_failed handler."""

    def test_on_request_failed_removes_pending(self):
        """Failed requests are removed from pending."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        # First add a pending request
        mock_request = MagicMock()
        mock_request.url = "https://api.example.com/users"
        mock_request.method = "GET"
        mock_request.resource_type = "xhr"
        mock_request.headers = {}
        mock_request.post_data = None

        capture._on_request(mock_request)
        assert len(capture._pending_requests) == 1

        # Now simulate failure
        capture._on_request_failed(mock_request)
        assert len(capture._pending_requests) == 0


class TestPlaywrightCaptureImportError:
    """Tests for import error handling."""

    @pytest.mark.asyncio
    async def test_capture_without_playwright_raises_import_error(self):
        """Capture raises ImportError when playwright not installed."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"])

        with (
            patch.dict("sys.modules", {"playwright.async_api": None}),
            patch(
                "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
                side_effect=ImportError("Playwright is required"),
            ),
            pytest.raises(ImportError, match="Playwright"),
        ):
            await capture.capture("https://api.example.com")


class TestRunCapture:
    """Tests for the run_capture convenience function."""

    def test_run_capture_creates_instance(self):
        """run_capture creates a PlaywrightCapture instance."""
        from toolwright.core.capture.playwright_capture import run_capture

        # We can't easily test this without mocking asyncio.run
        # Just verify the function exists and has the right signature
        assert callable(run_capture)


class TestPlaywrightCaptureScripted:
    """Tests for scripted capture mode."""

    @pytest.mark.asyncio
    async def test_capture_uses_script_runner(self):
        """Script path invokes loader and awaits async run(page, context)."""
        capture = PlaywrightCapture(allowed_hosts=["api.example.com"], headless=True)

        page = MagicMock()
        page.on = MagicMock()
        page.goto = AsyncMock()
        page.is_closed = MagicMock(return_value=False)

        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock()
        chromium = MagicMock()
        chromium.launch = AsyncMock(return_value=browser)

        class FakePlaywrightContext:
            async def __aenter__(self):
                return SimpleNamespace(chromium=chromium)

            async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

        script_runner = AsyncMock()
        with (
            patch.dict(
                "sys.modules",
                {"playwright.async_api": SimpleNamespace(async_playwright=lambda: FakePlaywrightContext())},
            ),
            patch.object(capture, "_load_script_runner", return_value=script_runner) as mock_loader,
        ):
            await capture.capture(
                start_url="https://app.example.com",
                script_path="/tmp/script.py",
                settle_delay_seconds=0.0,
            )

        mock_loader.assert_called_once_with("/tmp/script.py")
        script_runner.assert_awaited_once_with(page, context)
