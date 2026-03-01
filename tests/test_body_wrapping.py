"""Tests for request body envelope wrapper detection and application."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint


def _make_endpoint(
    method: str = "POST",
    path: str = "/admin/api/products.json",
    host: str = "myshop.myshopify.com",
    request_body_schema: dict | None = None,
) -> Endpoint:
    """Create a minimal Endpoint for testing."""
    return Endpoint(
        method=method,
        path=path,
        host=host,
        request_body_schema=request_body_schema,
    )


class TestWrapperDetection:
    """Part A: Detect envelope wrapper during compile."""

    def test_shopify_product_wrapper_detected(self):
        """Single top-level object property detected as wrapper key."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "vendor": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert action.get("request_body_wrapper") == "product"

    def test_flat_single_string_property_not_wrapped(self):
        """Single scalar property is NOT a wrapper."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert "request_body_wrapper" not in action

    def test_multi_property_body_not_wrapped(self):
        """Multiple top-level properties are NOT a wrapper."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "vendor": {"type": "string"},
                "price": {"type": "number"},
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert "request_body_wrapper" not in action

    def test_wrapper_inner_properties_flattened(self):
        """Inner properties (title, vendor) are in input_schema; wrapper key (product) is NOT."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "vendor": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]
        props = action["input_schema"]["properties"]

        # Inner properties should be flattened into the input schema
        assert "title" in props
        assert "vendor" in props
        # The wrapper key itself should NOT appear as a property
        assert "product" not in props

    def test_no_body_schema_no_wrapper(self):
        """No request_body_schema means no wrapper."""
        endpoint = _make_endpoint(request_body_schema=None)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert "request_body_wrapper" not in action

    def test_empty_body_schema_no_wrapper(self):
        """Empty request_body_schema means no wrapper."""
        schema: dict = {}
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert "request_body_wrapper" not in action

    def test_object_without_sub_properties_not_wrapped(self):
        """Single object property WITHOUT nested properties is NOT a wrapper.

        e.g. {"metadata": {"type": "object"}} has no inner properties to flatten,
        so it should not be treated as an envelope wrapper.
        """
        schema = {
            "type": "object",
            "properties": {
                "metadata": {
                    "type": "object",
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        assert "request_body_wrapper" not in action


class TestWrapperRoundTrip:
    """Part B: Compiled action wrapper key used at execution time.

    These tests simulate the wrapping logic from server.py's build_url_and_kwargs()
    closure inline, rather than invoking the actual server code. This verifies the
    contract: if request_body_wrapper is set, the body params are wrapped in
    {wrapper_key: params}.
    """

    def test_wrapper_key_stored_and_retrievable(self):
        """Compiled action has request_body_wrapper that can be used at execution time."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        # Simulate execution-time wrapping logic
        args = {"title": "Test Product"}
        wrapper = action.get("request_body_wrapper")
        if wrapper:
            body = {wrapper: args}
        else:
            body = args

        assert body == {"product": {"title": "Test Product"}}

    def test_no_wrapper_passes_args_flat(self):
        """Without wrapper, args pass through flat."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "vendor": {"type": "string"},
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        generator = ToolManifestGenerator()
        manifest = generator.generate([endpoint])
        action = manifest["actions"][0]

        args = {"title": "Test Product", "vendor": "ACME"}
        wrapper = action.get("request_body_wrapper")
        if wrapper:
            body = {wrapper: args}
        else:
            body = args

        assert body == {"title": "Test Product", "vendor": "ACME"}
