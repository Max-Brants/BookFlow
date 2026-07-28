"""Server-side GitHub issue creation for in-app problem reports."""

from __future__ import annotations

import base64
import io
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

GITHUB_API_VERSION = "2026-03-10"
ATTACHMENT_BRANCH = "bookflow-issue-attachments"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_NORMALIZED_IMAGE_BYTES = 10 * 1024 * 1024
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class IssueReportingError(RuntimeError):
    """A safe, classified failure from the GitHub integration."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ImageValidationError(ValueError):
    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.too_large = too_large


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    content: bytes
    extension: str
    media_type: str
    source_media_type: str


@dataclass(frozen=True, slots=True)
class CreatedIssue:
    number: int
    body: str


def valid_repository(repository: str) -> bool:
    return bool(_REPOSITORY_PATTERN.fullmatch(repository.strip()))


def normalize_image(raw: bytes) -> NormalizedImage:
    """Validate and re-encode an uploaded image, stripping all metadata."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageValidationError("Afbeelding is groter dan 5 MiB", too_large=True)
    if not raw:
        raise ImageValidationError("Afbeelding is leeg")

    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageValidationError(
                    "Alleen PNG-, JPEG- en WebP-afbeeldingen zijn toegestaan"
                )
            source_media_type = {
                "PNG": "image/png",
                "JPEG": "image/jpeg",
                "WEBP": "image/webp",
            }[source.format]
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ImageValidationError("Afbeelding heeft te veel pixels", too_large=True)
            source.load()
            transposed = ImageOps.exif_transpose(source)
            has_alpha = transposed.mode in {"RGBA", "LA"} or (
                transposed.mode == "P" and "transparency" in transposed.info
            )
            output = io.BytesIO()
            if has_alpha:
                clean = transposed.convert("RGBA")
                clean.save(output, format="PNG", optimize=True)
                extension = "png"
                media_type = "image/png"
            else:
                clean = transposed.convert("RGB")
                clean.save(output, format="JPEG", quality=90, optimize=True)
                extension = "jpg"
                media_type = "image/jpeg"
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError("Ongeldig of beschadigd afbeeldingsbestand") from exc
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("Afbeelding heeft te veel pixels", too_large=True) from exc

    normalized = output.getvalue()
    if len(normalized) > MAX_NORMALIZED_IMAGE_BYTES:
        raise ImageValidationError("Verwerkte afbeelding is te groot", too_large=True)
    return NormalizedImage(normalized, extension, media_type, source_media_type)


def _inline_code(value: str, *, maximum: int) -> str:
    normalized = " ".join(value.split())[:maximum]
    return f"`{normalized.replace('`', 'ˋ')}`"


def build_issue_body(
    *,
    description: str,
    page_url: str,
    username: str,
    build_version: str,
    release_version: str,
    submitted_at: str,
    user_agent: str,
    ui_language: str,
) -> str:
    return "\n".join(
        (
            "## Omschrijving",
            "",
            description.strip(),
            "",
            "## Context",
            "",
            f"- Pagina: {_inline_code(page_url, maximum=2048)}",
            f"- BookFlow-gebruiker: {_inline_code(username, maximum=200)}",
            f"- Build: {_inline_code(build_version, maximum=100)}",
            f"- Release: {_inline_code(release_version, maximum=100)}",
            f"- Tijdstip: {_inline_code(submitted_at, maximum=100)}",
            f"- Browser: {_inline_code(user_agent, maximum=500)}",
            f"- UI-taal: {_inline_code(ui_language, maximum=20)}",
            "",
            "_Automatisch ingediend vanuit BookFlow._",
        )
    )


class GitHubIssueService:
    def __init__(
        self,
        *,
        token: str,
        repository: str,
        session: requests.Session | None = None,
    ) -> None:
        if not token.strip() or not valid_repository(repository):
            raise ValueError("Invalid GitHub issue reporting configuration")
        self._repository = repository.strip()
        self._owner, self._repo = self._repository.split("/", 1)
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token.strip()}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": "BookFlow-Issue-Reporter",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = self._session.request(
                method,
                f"https://api.github.com/repos/{self._owner}/{self._repo}{path}",
                timeout=(5, 20),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise IssueReportingError(
                "github_unavailable", "GitHub is momenteel niet bereikbaar", 503
            ) from exc
        return response

    @staticmethod
    def _raise_for_response(response: requests.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code in {401, 403}:
            raise IssueReportingError(
                "github_auth_failed", "GitHub-configuratie heeft onvoldoende rechten", 503
            )
        if response.status_code in {404, 410}:
            raise IssueReportingError(
                "github_repository_unavailable",
                "De GitHub-repository of issuefunctie is niet beschikbaar",
                503,
            )
        if response.status_code == 429:
            raise IssueReportingError(
                "github_rate_limited", "GitHub accepteert tijdelijk geen nieuwe meldingen", 503
            )
        raise IssueReportingError(
            "github_request_failed", "GitHub kon de probleemmelding niet verwerken", 502
        )

    @staticmethod
    def _json_object(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (requests.JSONDecodeError, ValueError) as exc:
            raise IssueReportingError(
                "github_invalid_response", "GitHub gaf geen geldig antwoord terug", 502
            ) from exc
        if not isinstance(payload, dict):
            raise IssueReportingError(
                "github_invalid_response", "GitHub gaf geen geldig antwoord terug", 502
            )
        return payload

    def create_issue(self, *, title: str, body: str) -> CreatedIssue:
        response = self._request(
            "POST", "/issues", json={"title": title, "body": body, "labels": ["needs-triage"]}
        )
        if response.status_code == 422 and self._missing_label_may_be_cause(response):
            response = self._request("POST", "/issues", json={"title": title, "body": body})
        self._raise_for_response(response)
        payload = self._json_object(response)
        number = payload.get("number")
        if not isinstance(number, int):
            raise IssueReportingError(
                "github_invalid_response", "GitHub gaf geen geldig issuenummer terug", 502
            )
        return CreatedIssue(number=number, body=body)

    @staticmethod
    def _missing_label_may_be_cause(response: requests.Response) -> bool:
        """Retry only label-related validation failures (plus opaque 422 test doubles)."""
        try:
            payload = response.json()
        except requests.JSONDecodeError:
            return True
        if not isinstance(payload, dict) or not payload:
            return True
        message = str(payload.get("message", "")).lower()
        if "label" in message:
            return True
        errors = payload.get("errors")
        return isinstance(errors, list) and any(
            isinstance(error, dict) and str(error.get("field", "")).lower() == "labels"
            for error in errors
        )

    def _ensure_attachment_branch(self) -> None:
        encoded_branch = quote(ATTACHMENT_BRANCH, safe="")
        branch_response = self._request("GET", f"/git/ref/heads/{encoded_branch}")
        if branch_response.status_code == 200:
            return
        if branch_response.status_code != 404:
            self._raise_for_response(branch_response)

        repository_response = self._request("GET", "")
        self._raise_for_response(repository_response)
        repository_payload = self._json_object(repository_response)
        default_branch = repository_payload.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise IssueReportingError(
                "github_invalid_response", "GitHub gaf geen standaardbranch terug", 502
            )
        base_response = self._request("GET", f"/git/ref/heads/{quote(default_branch, safe='')}")
        self._raise_for_response(base_response)
        base_payload = self._json_object(base_response)
        sha = (
            base_payload.get("object", {}).get("sha")
            if isinstance(base_payload.get("object"), dict)
            else None
        )
        if not isinstance(sha, str):
            raise IssueReportingError(
                "github_invalid_response", "GitHub gaf geen geldige branchreferentie terug", 502
            )
        create_response = self._request(
            "POST",
            "/git/refs",
            json={"ref": f"refs/heads/{ATTACHMENT_BRANCH}", "sha": sha},
        )
        if create_response.status_code == 422:
            retry = self._request("GET", f"/git/ref/heads/{encoded_branch}")
            self._raise_for_response(retry)
            return
        self._raise_for_response(create_response)

    def attach_image(self, *, issue: CreatedIssue, image: NormalizedImage) -> str:
        self._ensure_attachment_branch()
        filename = f"{uuid.uuid4().hex}.{image.extension}"
        path = f"issue-attachments/{issue.number}/{filename}"
        upload_response = self._request(
            "PUT",
            f"/contents/{quote(path, safe='/')}",
            json={
                "message": f"Add attachment for issue #{issue.number}",
                "content": base64.b64encode(image.content).decode("ascii"),
                "branch": ATTACHMENT_BRANCH,
            },
        )
        self._raise_for_response(upload_response)
        attachment_url = (
            f"https://github.com/{self._repository}/blob/"
            f"{ATTACHMENT_BRANCH}/{quote(path, safe='/')}"
        )
        updated_body = (
            f"{issue.body}\n\n## Bijlage\n\n"
            f"[Screenshot bij probleemmelding #{issue.number}]({attachment_url})"
        )
        update_response = self._request(
            "PATCH", f"/issues/{issue.number}", json={"body": updated_body}
        )
        self._raise_for_response(update_response)
        return attachment_url
