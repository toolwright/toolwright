"""Tests for HAR parser."""

import json
import tempfile
from pathlib import Path

from toolwright.core.capture.har_parser import HARParser
from toolwright.models.capture import CaptureSource


def create_har_file(entries: list[dict]) -> Path:
    """Create a temporary HAR file with given entries."""
    har_data = {
        "log": {
            "version": "1.2",
            "entries": entries,
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(har_data, f)
        return Path(f.name)


def make_entry(
    url: str,
    method: str = "GET",
    status: int = 200,
    content_type: str = "application/json",
    request_body: str | None = None,
    response_body: str | None = None,
) -> dict:
    """Create a HAR entry."""
    entry = {
        "request": {
            "method": method,
            "url": url,
            "headers": [],
        },
        "response": {
            "status": status,
            "headers": [{"name": "content-type", "value": content_type}],
            "content": {},
        },
        "_resourceType": "xhr",
    }

    if request_body:
        entry["request"]["postData"] = {"text": request_body}
    if response_body:
        entry["response"]["content"]["text"] = response_body

    return entry


class TestHARParser:
    """Tests for HARParser."""

    def test_parse_empty_har(self):
        """Test parsing an empty HAR file."""
        har_path = create_har_file([])
        parser = HARParser(allowed_hosts=["api.example.com"])

        session = parser.parse_file(har_path)

        assert session.source == CaptureSource.HAR
        assert len(session.exchanges) == 0
        assert session.total_requests == 0

        har_path.unlink()

    def test_parse_single_request(self):
        """Test parsing a HAR with a single request."""
        entries = [
            make_entry(
                url="https://api.example.com/users/123",
                method="GET",
                status=200,
                response_body='{"id": 123, "name": "John"}',
            )
        ]
        har_path = create_har_file(entries)
        parser = HARParser(allowed_hosts=["api.example.com"])

        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 1
        assert session.exchanges[0].url == "https://api.example.com/users/123"
        assert session.exchanges[0].method.value == "GET"
        assert session.exchanges[0].response_status == 200

        har_path.unlink()

    def test_filter_by_allowed_hosts(self):
        """Test that requests to non-allowed hosts are filtered."""
        entries = [
            make_entry(url="https://api.example.com/users"),
            make_entry(url="https://analytics.tracking.com/event"),
            make_entry(url="https://cdn.example.com/static.js"),
        ]
        har_path = create_har_file(entries)
        parser = HARParser(allowed_hosts=["api.example.com"])

        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 1
        assert session.exchanges[0].host == "api.example.com"
        assert session.filtered_requests == 2

        har_path.unlink()

    def test_wildcard_host_matching(self):
        """Test wildcard host matching."""
        entries = [
            make_entry(url="https://api.example.com/users"),
            make_entry(url="https://api2.example.com/orders"),
            make_entry(url="https://other.com/data"),
        ]
        har_path = create_har_file(entries)
        parser = HARParser(allowed_hosts=["*.example.com"])

        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 2
        hosts = {e.host for e in session.exchanges}
        assert hosts == {"api.example.com", "api2.example.com"}

        har_path.unlink()

    def test_filter_static_files(self):
        """Test that static files are filtered out."""
        entries = [
            make_entry(url="https://api.example.com/users"),
            make_entry(url="https://api.example.com/styles.css"),
            make_entry(url="https://api.example.com/logo.png"),
            make_entry(url="https://api.example.com/app.js"),
        ]
        har_path = create_har_file(entries)
        parser = HARParser(allowed_hosts=["api.example.com"])

        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 1
        assert "/users" in session.exchanges[0].url

        har_path.unlink()

    def test_parse_json_bodies(self):
        """Test that JSON bodies are parsed."""
        entries = [
            make_entry(
                url="https://api.example.com/users",
                method="POST",
                request_body='{"name": "John", "email": "john@example.com"}',
                response_body='{"id": 123}',
            )
        ]
        har_path = create_har_file(entries)
        parser = HARParser(allowed_hosts=["api.example.com"])

        session = parser.parse_file(har_path)

        exchange = session.exchanges[0]
        assert exchange.request_body_json == {"name": "John", "email": "john@example.com"}
        assert exchange.response_body_json == {"id": 123}

        har_path.unlink()


class TestPathNormalizer:
    """Tests for path normalization."""

    def test_normalize_uuid(self):
        """Test UUID normalization."""
        from toolwright.core.normalize.path_normalizer import PathNormalizer

        normalizer = PathNormalizer()

        path = "/users/550e8400-e29b-41d4-a716-446655440000"
        result = normalizer.normalize(path)

        assert result == "/users/{uuid}"

    def test_normalize_numeric_id(self):
        """Test numeric ID normalization."""
        from toolwright.core.normalize.path_normalizer import PathNormalizer

        normalizer = PathNormalizer()

        path = "/users/123/orders/456"
        result = normalizer.normalize(path)

        assert result == "/users/{id}/orders/{id}"

    def test_preserve_version_segments(self):
        """Test that version segments are preserved."""
        from toolwright.core.normalize.path_normalizer import PathNormalizer

        normalizer = PathNormalizer()

        path = "/api/v1/users/123"
        result = normalizer.normalize(path)

        assert result == "/api/v1/users/{id}"

    def test_extract_parameters(self):
        """Test parameter extraction from path."""
        from toolwright.core.normalize.path_normalizer import PathNormalizer

        normalizer = PathNormalizer()

        template = "/users/{id}/orders/{order_id}"
        path = "/users/123/orders/456"

        params = normalizer.extract_parameters(template, path)

        assert params == {"id": "123", "order_id": "456"}


class TestToolNaming:
    """Tests for tool naming utilities."""

    def test_get_single_resource(self):
        """Test naming for GET single resource."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("GET", "/users/{id}")
        assert name == "get_user"

    def test_list_resources(self):
        """Test naming for GET collection."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("GET", "/users")
        assert name == "get_users"

    def test_create_resource(self):
        """Test naming for POST."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("POST", "/users")
        assert name == "create_user"

    def test_delete_resource(self):
        """Test naming for DELETE."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("DELETE", "/users/{id}")
        assert name == "delete_user"

    def test_nested_resource(self):
        """Test naming for nested resources."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("GET", "/products/{id}/reviews")
        assert name == "get_product_reviews"

    def test_search_override(self):
        """Test verb override for search."""
        from toolwright.utils.naming import generate_tool_name

        # Search is a read-only POST, so keeps plural
        name = generate_tool_name("POST", "/search/products")
        assert name == "search_products"

    def test_graphql_override(self):
        """Test verb override for GraphQL."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("POST", "/graphql")
        assert name == "query"

    def test_strips_api_prefix(self):
        """Test that api prefix is stripped."""
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("GET", "/api/v1/users/{id}")
        assert name == "get_user"
