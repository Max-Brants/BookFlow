"""Reader-shaped requests: initialization, auth, delta sync, files and bookmarks.

Wire shapes are based on the Kobo Store API as implemented by Calibre-Web,
not the former synthetic BookFlow contract. Physical firmware acceptance is
recorded separately in docs/kobo.md.
"""

from urllib.parse import urlsplit

import pytest
from flask import Flask

from bookflow.core.kobo_pairing import KoboPairingService
from bookflow.core.kobo_pairing_routes import register_kobo_pairing_routes
from bookflow.core.kobo_protocol import book_uuid
from bookflow.core.kobo_routes import register_kobo_routes

from .test_auth_api import main_module as main_module
from .test_kobo_services import kobo_fixture as kobo_fixture


def _reader(fixture, guard=None):
    app = Flask(__name__)
    if guard:
        app.before_request(guard)
    register_kobo_routes(
        app,
        token_service=fixture["tokens"],
        sync_service=fixture["sync"],
        allowed_file_roots=(fixture["storage_root"],),
        tls_guard=lambda: True,
        cover_fetcher=lambda *_: (b"image", "image/jpeg"),
    )
    user_id = fixture["user"]["id"]
    fixture["sync"].set_book(
        user_id=user_id, book_id=fixture["book_id"], file_id=fixture["file_id"]
    )
    token = fixture["tokens"].issue_token(user_id=user_id)
    return app.test_client(), f"/api/kobo/{token.token}"


def test_reader_discovers_resources_authenticates_and_downloads(kobo_fixture):
    client, base = _reader(kobo_fixture)
    init = client.get(base + "/v1/initialization", base_url="https://books.example")
    assert init.status_code == 200
    assert init.headers["x-kobo-apitoken"] == "e30="
    resources = init.json["Resources"]
    assert resources["library_sync"] == "https://books.example" + base + "/v1/library/sync"
    assert "{Ids}" in resources["library_metadata"]
    auth = client.post(
        urlsplit(resources["device_auth"]).path,
        json={"DeviceId": "Kobo-Glo", "UserKey": "device-user"},
    )
    assert auth.status_code == 200
    assert {"AccessToken", "RefreshToken", "TokenType", "TrackingId", "UserKey"} <= auth.json.keys()
    sync = client.get(base + "/v1/library/sync", base_url="https://books.example")
    assert isinstance(sync.json, list)
    item = sync.json[0]["NewEntitlement"]
    metadata = item["BookMetadata"]
    identifier = metadata["RevisionId"]
    assert identifier == item["BookEntitlement"]["Id"] == book_uuid(kobo_fixture["book_id"])
    assert {url["Format"] for url in metadata["DownloadUrls"]} == {"EPUB", "EPUB3"}
    for download in metadata["DownloadUrls"]:
        assert download["Url"].startswith("https://books.example" + base)
        assert download["Platform"] == "Generic"
        assert client.get(urlsplit(download["Url"]).path).data == b"synthetic kobo ebook"
    assert client.get(
        base + f"/v1/library/{identifier}/metadata", base_url="https://books.example"
    ).json == [metadata]
    cover = resources["image_url_quality_template"].format(
        ImageId=identifier, Width=600, Height=800, Quality=90, IsGreyscale="true"
    )
    assert client.get(urlsplit(cover).path).data == b"image"
    assert client.get(base).json["Resources"]
    assert sync.headers["Cache-Control"] == "private, no-store"


def test_idle_sync_keeps_cursor_and_new_change_is_delivered(kobo_fixture):
    client, base = _reader(kobo_fixture)
    first = client.get(base + "/v1/library/sync")
    headers = {"X-Kobo-Synctoken": first.headers["X-Kobo-Synctoken"]}
    idle = client.get(base + "/v1/library/sync", headers=headers)
    assert idle.json == []
    assert idle.headers["X-Kobo-Synctoken"] == headers["X-Kobo-Synctoken"]
    kobo_fixture["sync"].set_reading_state(
        user_id=kobo_fixture["user"]["id"], book_id=kobo_fixture["book_id"], progress=45
    )
    delta = client.get(base + "/v1/library/sync", headers=headers)
    assert (
        delta.json[0]["ChangedReadingState"]["ReadingState"]["CurrentBookmark"]["ProgressPercent"]
        == 45
    )
    kobo_fixture["sync"].delete_book(
        user_id=kobo_fixture["user"]["id"], book_id=kobo_fixture["book_id"]
    )
    removed = client.get(
        base + "/v1/library/sync", headers={"X-Kobo-Synctoken": delta.headers["X-Kobo-Synctoken"]}
    )
    assert removed.json[0]["ChangedEntitlement"]["BookEntitlement"]["IsRemoved"] is True
    assert client.get(base + f"/v1/files/{kobo_fixture['file_id']}/download").status_code == 404


def test_reader_bookmark_roundtrip_and_stale_state_does_not_reset(kobo_fixture):
    client, base = _reader(kobo_fixture)
    identifier = book_uuid(kobo_fixture["book_id"])
    url = base + f"/v1/library/{identifier}/state"
    state = {
        "EntitlementId": identifier,
        "CurrentBookmark": {
            "ProgressPercent": 42,
            "ContentSourceProgressPercent": 42,
            "Location": {"Value": "chapter3.xhtml#p10", "Type": "KoboSpan", "Source": "kepub"},
        },
        "StatusInfo": {"Status": "Reading"},
        "Statistics": {"SpentReadingMinutes": 15},
    }
    result = client.put(url, json={"ReadingStates": [state]})
    assert result.status_code == 200
    assert result.json["RequestResult"] == "Success"
    read = client.get(url).json[0]
    assert read["CurrentBookmark"]["Location"] == state["CurrentBookmark"]["Location"]
    assert read["Statistics"]["SpentReadingMinutes"] == 15
    assert (
        client.put(
            url, json={"ReadingStates": [{"CurrentBookmark": {"ProgressPercent": 5}}]}
        ).status_code
        == 200
    )
    assert client.get(url).json[0]["CurrentBookmark"]["ProgressPercent"] == 42
    assert client.delete(base + f"/v1/library/{identifier}").status_code == 200
    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"ReadingStates": []},
        {"ReadingStates": [{"CurrentBookmark": {"ProgressPercent": True}}]},
        {"ReadingStates": [{"CurrentBookmark": {"ProgressPercent": -1}}]},
        {"ReadingStates": [{"CurrentBookmark": []}]},
        {"ReadingStates": [{"EntitlementId": "another-book"}]},
    ],
)
def test_malformed_native_state_is_rejected(kobo_fixture, payload):
    client, base = _reader(kobo_fixture)
    response = client.put(
        base + f"/v1/library/{book_uuid(kobo_fixture['book_id'])}/state", json=payload
    )
    assert response.status_code == 400


def test_native_tokens_and_entitlements_do_not_cross_users(kobo_fixture):
    client, base = _reader(kobo_fixture)
    cursor = client.get(base + "/v1/library/sync").headers["X-Kobo-Synctoken"]
    other = kobo_fixture["tokens"].issue_token(user_id=kobo_fixture["other_user"]["id"])
    other_base = f"/api/kobo/{other.token}"
    for method, path in [
        ("get", "/v1/library/sync"),
        ("get", "/v1/initialization"),
        ("post", "/v1/auth/device"),
        ("post", "/v1/user/add-device"),
    ]:
        assert getattr(client, method)("/api/kobo/invalid-token" + path, json={}).status_code == 401
    assert (
        client.get(
            other_base + "/v1/library/sync", headers={"X-Kobo-Synctoken": cursor}
        ).status_code
        == 409
    )
    assert (
        client.get(
            base + "/v1/library/sync", headers={"X-Kobo-Synctoken": cursor + "broken"}
        ).status_code
        == 409
    )
    assert (
        client.get(
            other_base + f"/v1/library/{book_uuid(kobo_fixture['book_id'])}/metadata"
        ).status_code
        == 404
    )
    assert (
        client.delete(other_base + f"/v1/library/{book_uuid(kobo_fixture['book_id'])}").status_code
        == 404
    )


def test_reader_pagination_resumes_after_restart_without_replaying(kobo_fixture):
    client, base = _reader(kobo_fixture)
    sync = kobo_fixture["sync"]
    for number in range(101):
        sync.set_reading_state(
            user_id=kobo_fixture["user"]["id"], book_id=kobo_fixture["book_id"], progress=number
        )
    page = client.get(base + "/v1/library/sync")
    assert page.headers["X-Kobo-Sync"] == "continue"
    resumed = client.get(
        base + "/v1/library/sync", headers={"X-Kobo-Synctoken": page.headers["X-Kobo-Synctoken"]}
    )
    assert "X-Kobo-Sync" not in resumed.headers
    # A new service instance (server restart) accepts the same signed checkpoint.
    restarted = type(sync)(str(kobo_fixture["db_path"]), cursor_secret="test-cursor-secret")
    checkpoint = resumed.headers["X-Kobo-Synctoken"].removeprefix("bf1.")
    assert (
        restarted.sync(
            user_id=kobo_fixture["user"]["id"], cursor=checkpoint, persistent=True
        ).changes
        == []
    )


def test_real_origin_guard_allows_token_requests_but_rejects_cross_site(
    kobo_fixture, main_module, monkeypatch
):
    monkeypatch.setitem(main_module.app.config, "ENFORCE_MUTATION_ORIGIN", True)
    client, base = _reader(kobo_fixture, main_module.enforce_browser_mutation_origin)
    assert client.post(base + "/v1/auth/device", json={"DeviceId": "Glo"}).status_code == 200
    assert client.post(base + "/v1/auth/refresh", json={}).status_code == 200
    assert client.post(base + "/v1/user/add-device", json={}).status_code == 200
    assert (
        client.post(
            base + "/v1/auth/device", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    # A cookie is not a substitute for the URL token.
    client.set_cookie("session", "irrelevant")
    assert client.post("/api/kobo/invalid-token/v1/auth/device", json={}).status_code == 401


def test_patcher_pairing_works_through_production_origin_guard(
    kobo_fixture, main_module, monkeypatch
):
    monkeypatch.setitem(main_module.app.config, "ENFORCE_MUTATION_ORIGIN", True)
    service = KoboPairingService(
        str(kobo_fixture["db_path"]),
        secret="pairing-secret" * 4,
        token_service=kobo_fixture["tokens"],
    )
    code = service.create_code(user_id=kobo_fixture["user"]["id"], origin="https://books.example")
    app = Flask(__name__)
    app.before_request(main_module.enforce_browser_mutation_origin)
    register_kobo_pairing_routes(
        app,
        resolve_actor=lambda: None,
        service=service,
        patcher_cache=kobo_fixture["storage_root"] / "kobopatcher",
    )
    client = app.test_client()
    claim = client.post(
        "/api/kobo/pair/claim", json={"code": code["code"]}, base_url="https://books.example"
    )
    assert claim.status_code == 200
    session = claim.json["pairing_session"]
    complete = client.post(
        "/api/kobo/pair/complete",
        json={"pairing_session": session, "device_label": "Glo"},
        base_url="https://books.example",
    )
    assert complete.status_code == 200
    assert complete.json["api_endpoint"].startswith("https://books.example/api/kobo/")
    revoke = client.delete(
        "/api/kobo/pair/session",
        json={"pairing_session": session},
        base_url="https://books.example",
    )
    assert revoke.json["revoked"] is True
    assert client.post("/api/v1/users/me/kobo-pairing-code").status_code == 403
