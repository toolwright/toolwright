"""Tests for draft toolpack creation from discovered specs."""

from __future__ import annotations

from datetime import UTC, datetime

from toolwright.core.discover.draft_toolpack import DraftToolpackCreator
from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)


def _make_session() -> CaptureSession:
    """Create a minimal CaptureSession for testing."""
    return CaptureSession(
        id="cap_test_123",
        name="Test API",
        description=None,
        created_at=datetime.now(UTC),
        source=CaptureSource.MANUAL,
        source_file=None,
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                id="ex_1",
                url="https://api.example.com/users",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/users",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=200,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
            HttpExchange(
                id="ex_2",
                url="https://api.example.com/users",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/users",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=201,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
            HttpExchange(
                id="ex_3",
                url="https://api.example.com/items",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/items",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=200,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
        ],
        total_requests=3,
        filtered_requests=0,
        redacted_count=0,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# TestCreateDraft
# ---------------------------------------------------------------------------


class TestCreateDraft:
    """Tests for DraftToolpackCreator.create()."""

    def test_creates_draft_directory(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        draft_dir = tmp_path / draft_id  # type: ignore[operator]
        assert draft_dir.is_dir()

    def test_creates_toolpack_yaml(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        assert (tmp_path / draft_id / "toolpack.yaml").is_file()  # type: ignore[operator]

    def test_toolpack_yaml_has_draft_marker(self, tmp_path: object) -> None:
        import yaml

        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        content = yaml.safe_load((tmp_path / draft_id / "toolpack.yaml").read_text())  # type: ignore[operator]
        assert content["draft"] is True

    def test_creates_tools_json(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        assert (tmp_path / draft_id / "tools.json").is_file()  # type: ignore[operator]

    def test_tools_json_has_actions(self, tmp_path: object) -> None:
        import json

        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        data = json.loads((tmp_path / draft_id / "tools.json").read_text())  # type: ignore[operator]
        assert "actions" in data
        assert len(data["actions"]) > 0

    def test_returns_draft_id(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        assert isinstance(draft_id, str)
        assert len(draft_id) > 0


# ---------------------------------------------------------------------------
# TestDraftActions
# ---------------------------------------------------------------------------


class TestDraftActions:
    """Tests for action generation from exchanges."""

    def test_actions_from_exchanges(self, tmp_path: object) -> None:
        import json

        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="test")
        data = json.loads((tmp_path / draft_id / "tools.json").read_text())  # type: ignore[operator]
        actions = data["actions"]
        # 3 exchanges but GET /users, POST /users, GET /items = 3 unique method+path
        assert len(actions) == 3
        for action in actions:
            assert "name" in action
            assert "method" in action
            assert "path" in action
            assert "host" in action

    def test_action_name_generated(self, tmp_path: object) -> None:
        import json

        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="test")
        data = json.loads((tmp_path / draft_id / "tools.json").read_text())  # type: ignore[operator]
        names = {a["name"] for a in data["actions"]}
        assert "get_users" in names
        assert "post_users" in names
        assert "get_items" in names

    def test_deduplicates_same_endpoint(self, tmp_path: object) -> None:
        import json

        session = _make_session()
        # Add a duplicate GET /users exchange
        session.exchanges.append(
            HttpExchange(
                id="ex_dup",
                url="https://api.example.com/users",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/users",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=200,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
        )
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(session, label="test")
        data = json.loads((tmp_path / draft_id / "tools.json").read_text())  # type: ignore[operator]
        # Still only 3 unique method+path combos
        assert len(data["actions"]) == 3


# ---------------------------------------------------------------------------
# TestListDrafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    """Tests for DraftToolpackCreator.list_drafts()."""

    def test_empty_when_no_drafts(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        assert creator.list_drafts() == []

    def test_lists_created_drafts(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        drafts = creator.list_drafts()
        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == draft_id

    def test_includes_metadata(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        creator.create(_make_session(), label="my-api")
        drafts = creator.list_drafts()
        draft = drafts[0]
        assert "draft_id" in draft
        assert "label" in draft
        assert "created_at" in draft
        assert "host" in draft
        assert draft["label"] == "my-api"
        assert draft["host"] == "api.example.com"


# ---------------------------------------------------------------------------
# TestGetDraftPath
# ---------------------------------------------------------------------------


class TestGetDraftPath:
    """Tests for DraftToolpackCreator.get_draft_path()."""

    def test_returns_path_when_exists(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        draft_id = creator.create(_make_session(), label="my-api")
        result = creator.get_draft_path(draft_id)
        assert result is not None
        assert result.is_dir()

    def test_returns_none_when_not_exists(self, tmp_path: object) -> None:
        creator = DraftToolpackCreator(drafts_root=tmp_path)  # type: ignore[arg-type]
        result = creator.get_draft_path("nonexistent_draft")
        assert result is None
