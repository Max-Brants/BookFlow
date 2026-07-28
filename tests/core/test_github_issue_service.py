"""Unit tests for the isolated GitHub issue reporting service."""

from __future__ import annotations

import io

import pytest
import requests
from PIL import Image

from bookflow.core.github_issue_service import (
    ATTACHMENT_BRANCH,
    MAX_IMAGE_BYTES,
    CreatedIssue,
    GitHubIssueService,
    ImageValidationError,
    IssueReportingError,
    build_issue_body,
    normalize_image,
)


def _image_bytes(*, fmt: str = "PNG", exif: bytes | None = None) -> bytes:
    image = Image.new("RGB", (4, 3), color="red")
    output = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def test_normalize_image_reencodes_and_strips_exif_metadata() -> None:
    exif = Image.Exif()
    exif[270] = "secret camera note"

    normalized = normalize_image(_image_bytes(fmt="JPEG", exif=exif.tobytes()))

    assert normalized.extension == "jpg"
    assert normalized.media_type == "image/jpeg"
    with Image.open(io.BytesIO(normalized.content)) as clean:
        assert clean.size == (4, 3)
        assert clean.getexif().get(270) is None
        assert "exif" not in clean.info


@pytest.mark.parametrize("raw", [b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
def test_normalize_image_rejects_bad_signature_or_truncated_image(raw: bytes) -> None:
    with pytest.raises(ImageValidationError, match="Ongeldig"):
        normalize_image(raw)


def test_normalize_image_rejects_raw_file_over_five_mib() -> None:
    with pytest.raises(ImageValidationError, match="5 MiB") as raised:
        normalize_image(b"x" * (MAX_IMAGE_BYTES + 1))

    assert raised.value.too_large is True


def test_normalize_image_rejects_pixel_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the fixture tiny while exercising the production pixel-limit branch.
    monkeypatch.setattr("bookflow.core.github_issue_service.MAX_IMAGE_PIXELS", 8)

    with pytest.raises(ImageValidationError, match="te veel pixels") as raised:
        normalize_image(_image_bytes())

    assert raised.value.too_large is True


def test_build_issue_body_includes_escaped_and_bounded_context() -> None:
    body = build_issue_body(
        description="  Het scherm blijft hangen.  ",
        page_url="https://example.test/a`b",
        username="reader\nname",
        build_version="b1",
        release_version="r1",
        submitted_at="2026-07-28T12:00:00+00:00",
        user_agent="Browser\n1",
        ui_language="nl",
    )

    assert "## Omschrijving\n\nHet scherm blijft hangen." in body
    assert "Pagina: `https://example.test/a" in body
    assert "a`b" not in body
    assert "BookFlow-gebruiker: `reader name`" in body
    assert "Browser: `Browser 1`" in body
    assert "UI-taal: `nl`" in body
    assert body.endswith("_Automatisch ingediend vanuit BookFlow._")


class _Response:
    def __init__(self, status_code: int, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[_Response | BaseException]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _Response:
        self.calls.append((method, url, kwargs))
        next_response = self.responses.pop(0)
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response


def _service(responses: list[_Response | BaseException]) -> tuple[GitHubIssueService, _FakeSession]:
    session = _FakeSession(responses)
    return GitHubIssueService(token="secret", repository="owner/private-repo", session=session), session


def test_create_issue_retries_without_label_when_label_is_missing() -> None:
    service, session = _service([_Response(422), _Response(201, {"number": 42})])

    result = service.create_issue(title="Broken", body="Details")

    assert result == CreatedIssue(number=42, body="Details")
    assert session.calls[0][2]["json"] == {
        "title": "Broken",
        "body": "Details",
        "labels": ["needs-triage"],
    }
    assert session.calls[1][2]["json"] == {"title": "Broken", "body": "Details"}
    assert session.calls[0][2]["timeout"] == (5, 20)


def test_create_issue_does_not_retry_non_label_validation_failure() -> None:
    service, session = _service(
        [
            _Response(
                422,
                {
                    "message": "Validation Failed",
                    "errors": [{"resource": "Issue", "field": "title", "code": "missing"}],
                },
            )
        ]
    )

    with pytest.raises(IssueReportingError, match="niet verwerken"):
        service.create_issue(title="Broken", body="Details")

    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "github_auth_failed"), (404, "github_repository_unavailable"), (429, "github_rate_limited")],
)
def test_create_issue_maps_github_errors_to_safe_errors(status: int, code: str) -> None:
    service, _session = _service([_Response(status)])

    with pytest.raises(IssueReportingError) as raised:
        service.create_issue(title="Broken", body="Details")

    assert raised.value.code == code
    assert raised.value.status_code == 503


def test_create_issue_maps_network_errors_to_service_unavailable() -> None:
    service, _session = _service([requests.ConnectionError("offline")])

    with pytest.raises(IssueReportingError) as raised:
        service.create_issue(title="Broken", body="Details")

    assert raised.value.code == "github_unavailable"
    assert raised.value.status_code == 503


def test_attach_image_creates_branch_uploads_and_updates_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    service, session = _service(
        [
            _Response(404),
            _Response(200, {"default_branch": "main"}),
            _Response(200, {"object": {"sha": "base-sha"}}),
            _Response(201),
            _Response(201),
            _Response(200),
        ]
    )
    monkeypatch.setattr("bookflow.core.github_issue_service.uuid.uuid4", lambda: type("U", (), {"hex": "abc"})())
    image = normalize_image(_image_bytes())

    attachment_url = service.attach_image(issue=CreatedIssue(7, "The body"), image=image)

    assert attachment_url.endswith(f"{ATTACHMENT_BRANCH}/issue-attachments/7/abc.jpg")
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET", "POST", "PUT", "PATCH"]
    assert session.calls[3][2]["json"] == {
        "ref": f"refs/heads/{ATTACHMENT_BRANCH}",
        "sha": "base-sha",
    }
    upload = session.calls[4][2]["json"]
    assert isinstance(upload, dict)
    assert upload["branch"] == ATTACHMENT_BRANCH
    patch = session.calls[5][2]["json"]
    assert isinstance(patch, dict)
    assert "## Bijlage" in patch["body"]
