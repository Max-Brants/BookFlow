"""Harness for the BookFlow end-to-end Docker platform.

These tests run against a live BookFlow booted by ``run-e2e.sh`` under a
particular configuration profile. Unmarked tests are profile-agnostic
invariants and therefore run across the whole configuration matrix.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

_SUITE_DIR = Path(__file__).resolve().parent

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8084")
ACTIVE_PROFILE = os.environ.get("E2E_PROFILE", "baseline")
DEFAULT_TIMEOUT = 15
DOWNLOAD_TIMEOUT = int(os.environ.get("E2E_DOWNLOAD_TIMEOUT", "120"))
TERMINAL_OK = {"complete", "done", "available"}
TERMINAL_ERR = {"error", "cancelled"}


@dataclass
class PlatformClient:
    base_url: str = BASE_URL
    timeout: int = DEFAULT_TIMEOUT
    session: requests.Session = field(default_factory=requests.Session)
    library_book_id: int | None = None

    def get(self, path: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        return self.session.get(f"{self.base_url}{path}", **kw)

    def post(self, path: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        return self.session.post(f"{self.base_url}{path}", **kw)

    def wait_for_health(self, max_wait: int = 90) -> bool:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                if self.get("/api/health").status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(2)
        return False

    def _ensure_catalog_book(self, query: str) -> int:
        """Seed canonical metadata for a black-box release-search scenario."""
        seed_script = """
import json
import os
import sqlite3
from pathlib import Path

from flask import Flask
from flask.sessions import SecureCookieSessionInterface

query = os.environ["E2E_BOOK_QUERY"]
provider_book_id = f"platform:{query.casefold()}"
with sqlite3.connect("/config/users.db", timeout=10) as connection:
    connection.execute(
        '''
        INSERT INTO books (
            metadata_provider, provider_book_id, title, author, language,
            metadata_json
        )
        VALUES ('e2e', ?, ?, 'BookFlow E2E', 'en', '{}')
        ON CONFLICT(metadata_provider, provider_book_id) DO UPDATE SET
            title = excluded.title
        ''',
        (provider_book_id, query),
    )
    row = connection.execute(
        '''
        SELECT id FROM books
        WHERE metadata_provider = 'e2e' AND provider_book_id = ?
        ''',
        (provider_book_id,),
    ).fetchone()
if row is None:
    raise RuntimeError(f"Could not seed E2E catalog book for {query!r}")

app = Flask("bookflow-e2e-session")
app.secret_key = Path("/config/.flask_secret").read_bytes()
serializer = SecureCookieSessionInterface().get_signing_serializer(app)
if serializer is None:
    raise RuntimeError("Could not create E2E session serializer")
print(json.dumps({"book_id": row[0], "session": serializer.dumps({"is_admin": True})}))
"""
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"E2E_BOOK_QUERY={query}",
                "e2e-bookflow",
                "/app/.venv/bin/python",
                "-c",
                seed_script,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not seed E2E catalog book for {query!r}: {result.stderr.strip()}"
            )
        seeded = json.loads(result.stdout)
        self.session.cookies.set("bookflow_session", str(seeded["session"]))
        return int(seeded["book_id"])

    def search_releases(
        self,
        query: str,
        *,
        source: str,
        inject: str | None = None,
        request_timeout: int = 60,
        **params,
    ) -> requests.Response:
        """Search releases through the canonical library-book API contract."""
        self.library_book_id = self._ensure_catalog_book(query)
        query_params = {
            "library_book_id": self.library_book_id,
            "source": source,
            **params,
        }
        if inject:
            query_params["manual_query"] = f"E2EINJECT:{inject} {query}"
        return self.get("/api/releases", params=query_params, timeout=request_timeout)

    def direct_search(
        self,
        query: str,
        *,
        inject: str | None = None,
        request_timeout: int = 60,
        **params,
    ) -> requests.Response:
        """Search the hermetic direct-download source for a canonical book."""
        return self.search_releases(
            query,
            source="direct_download",
            inject=inject,
            request_timeout=request_timeout,
            **params,
        )

    def releases_from(self, resp: requests.Response) -> list[dict]:
        if resp.status_code != 200:
            return []
        data = resp.json()
        if isinstance(data, dict):
            releases = data.get("releases")
            return releases if isinstance(releases, list) else []
        return data if isinstance(data, list) else []

    def queue_download(self, release: dict) -> requests.Response:
        payload = dict(release)
        if self.library_book_id is not None:
            payload["library_book_id"] = self.library_book_id
        return self.post("/api/releases/download", json=payload, timeout=30)

    def wait_for_terminal(self, book_id: str, timeout: int = DOWNLOAD_TIMEOUT) -> tuple[str, dict]:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            resp = self.get("/api/status")
            if resp.status_code == 200 and isinstance(resp.json(), dict):
                status = resp.json()
                for state, entries in status.items():
                    if isinstance(entries, dict) and book_id in entries:
                        last = entries[book_id]
                        if state in TERMINAL_OK or state in TERMINAL_ERR:
                            return state, last
            time.sleep(2)
        return "timeout", last


@pytest.fixture(scope="session")
def client() -> PlatformClient:
    platform_client = PlatformClient()
    platform_client.session.headers["Origin"] = BASE_URL
    if not platform_client.wait_for_health():
        pytest.fail(f"BookFlow not healthy at {BASE_URL} (profile={ACTIVE_PROFILE})")
    return platform_client


@pytest.fixture(scope="session")
def active_profile() -> str:
    return ACTIVE_PROFILE


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "platform: BookFlow e2e docker platform test")
    config.addinivalue_line("markers", "profiles(*names): only run under these E2E_PROFILE values")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests whose declared profiles do not include the active profile."""
    for item in items:
        if not item.path.is_relative_to(_SUITE_DIR):
            continue
        item.add_marker(pytest.mark.platform)
        item.add_marker(pytest.mark.e2e)
        marker = item.get_closest_marker("profiles")
        if marker and ACTIVE_PROFILE not in marker.args:
            item.add_marker(
                pytest.mark.skip(reason=f"profile={ACTIVE_PROFILE!r} not in {marker.args}")
            )
