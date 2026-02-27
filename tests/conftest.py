"""Shared test fixtures for Cask test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolwright.models.endpoint import AuthType, Endpoint
from tests.helpers import write_demo_artifacts, write_demo_toolpack


@pytest.fixture
def demo_toolpack(tmp_path: Path) -> Path:
    """Create a minimal demo toolpack and return toolpack.yaml path."""
    return write_demo_toolpack(tmp_path)


@pytest.fixture
def demo_artifacts(tmp_path: Path) -> dict[str, Path]:
    """Create minimal demo artifacts and return paths dict."""
    artifact_dir = tmp_path / "artifacts"
    return write_demo_artifacts(artifact_dir)


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users",
    host: str = "api.example.com",
    auth_type: AuthType = AuthType.NONE,
    parameters: list | None = None,
    is_state_changing: bool = False,
    response_body_json_schema: dict | None = None,
    tags: list[str] | None = None,
) -> Endpoint:
    """Create an Endpoint for testing.

    This is a module-level function (not a fixture) so it can be called
    with custom arguments. Import it directly:

        from tests.conftest import make_endpoint
    """
    return Endpoint(
        method=method,
        path=path,
        host=host,
        auth_type=auth_type,
        parameters=parameters or [],
        is_state_changing=is_state_changing,
        response_body_json_schema=response_body_json_schema,
        tags=tags or [],
    )
