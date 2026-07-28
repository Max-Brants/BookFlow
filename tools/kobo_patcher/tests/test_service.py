# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, S101

from pathlib import Path

import pytest
from kobo_patcher.conf import OFFICIAL_KOBO_ENDPOINT
from kobo_patcher.device import KoboDevice
from kobo_patcher.service import KoboPatcher, PatchError


def make_device(tmp_path: Path, config: bytes) -> KoboDevice:
    conf = tmp_path / ".kobo" / "Kobo" / "Kobo eReader.conf"
    conf.parent.mkdir(parents=True)
    conf.write_bytes(config)
    (tmp_path / ".kobo" / "KoboReader.sqlite").write_bytes(b"never open this")
    (tmp_path / ".kobo" / "version").write_text("firmware=4.40\n")
    return KoboDevice(tmp_path, "Test Kobo", "4.40", None, None)


def test_patch_creates_original_and_timestamp_backups_and_restore(tmp_path):
    source = b"[OneStoreServices]\r\napi_endpoint=https://before.example\r\nfoo=keep\r\n"
    patcher = KoboPatcher(make_device(tmp_path, source))
    result = patcher.patch("https://bookflow.example/api/kobo/abc")
    assert patcher.original_backup_path.read_bytes() == source
    assert result.backup_path.read_bytes() == source
    assert b"https://bookflow.example/api/kobo/abc" in patcher.path.read_bytes()
    restored = patcher.restore_backup()
    assert patcher.path.read_bytes() == source
    assert restored.backup_path.exists()
    assert patcher.original_backup_path.exists()


def test_patch_never_opens_or_changes_sqlite_database(tmp_path, monkeypatch):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    device = make_device(tmp_path, source)
    database = tmp_path / ".kobo" / "KoboReader.sqlite"
    original_database = database.read_bytes()
    path_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path == database:
            raise AssertionError("KoboReader.sqlite must never be opened")
        return path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    KoboPatcher(device).patch("https://bookflow.example/api/kobo/abc")
    with path_open(database, "rb") as stream:
        assert stream.read() == original_database


def test_official_restore_works_without_backups_or_section(tmp_path):
    source = b"[General]\nname=reader\n"
    patcher = KoboPatcher(make_device(tmp_path, source))
    result = patcher.restore_official_sync()
    assert result.endpoint == OFFICIAL_KOBO_ENDPOINT
    assert (
        patcher.path.read_bytes()
        == b"[General]\nname=reader\n[OneStoreServices]\napi_endpoint=https://storeapi.kobo.com\n"
    )
    assert result.backup_path.read_bytes() == source


def test_patch_requires_existing_target_section(tmp_path):
    patcher = KoboPatcher(make_device(tmp_path, b"[General]\nname=reader\n"))
    with pytest.raises(PatchError, match="missing"):
        patcher.patch("https://bookflow.example/api/kobo/abc")
    assert not patcher.original_backup_path.exists()


def test_restore_rejects_unrelated_path(tmp_path):
    patcher = KoboPatcher(make_device(tmp_path, b"[OneStoreServices]\napi_endpoint=before\n"))
    untrusted = tmp_path / "other.backup"
    untrusted.write_text("[OneStoreServices]\n")
    with pytest.raises(PatchError, match="No valid"):
        patcher.restore_backup(untrusted)


def test_restore_rejects_named_backup_without_ini_structure(tmp_path):
    patcher = KoboPatcher(make_device(tmp_path, b"[OneStoreServices]\napi_endpoint=before\n"))
    patcher.original_backup_path.write_text("not an ini document", encoding="utf-8")
    with pytest.raises(PatchError, match="not a usable"):
        patcher.restore_backup()


def test_write_verification_failure_rolls_back_original_config(tmp_path, monkeypatch):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    patcher = KoboPatcher(make_device(tmp_path, source))

    def fail_verification(_expected):
        raise PatchError("simulated interrupted write")

    monkeypatch.setattr(patcher, "_verify_written", fail_verification)
    with pytest.raises(PatchError, match="simulated"):
        patcher.patch("https://bookflow.example/api/kobo/abc")
    assert patcher.path.read_bytes() == source


def test_rollback_failure_is_explicit_and_tells_user_not_to_eject(tmp_path, monkeypatch):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    patcher = KoboPatcher(make_device(tmp_path, source))
    original_replace = Path.replace
    replacements = 0

    def replace_then_fail_rollback(path, target):
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise PermissionError("rollback replace denied")
        return original_replace(path, target)

    monkeypatch.setattr(
        patcher,
        "_verify_written",
        lambda _expected: (_ for _ in ()).throw(PatchError("simulated write failure")),
    )
    monkeypatch.setattr(Path, "replace", replace_then_fail_rollback)
    with pytest.raises(PatchError, match="automatic rollback also failed.*Do not eject"):
        patcher.patch("https://bookflow.example/api/kobo/abc")


def test_available_backups_ignores_symlinks(tmp_path):
    patcher = KoboPatcher(make_device(tmp_path, b"[OneStoreServices]\napi_endpoint=before\n"))
    target = tmp_path / "other.backup"
    target.write_text("[General]\nname=other\n", encoding="utf-8")
    symlink = patcher.original_backup_path
    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are unavailable in this Windows test environment")
    assert symlink not in patcher.available_backups()


def test_temporary_write_permission_failure_leaves_config_unchanged(tmp_path, monkeypatch):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    patcher = KoboPatcher(make_device(tmp_path, source))

    def denied(*_args, **_kwargs):
        raise PermissionError("read-only volume")

    monkeypatch.setattr("kobo_patcher.service.tempfile.mkstemp", denied)
    with pytest.raises(PatchError, match="temporary Kobo"):
        patcher.patch("https://bookflow.example/api/kobo/abc")
    assert patcher.path.read_bytes() == source


def test_replace_failure_leaves_config_unchanged_and_cleans_temporary_file(tmp_path, monkeypatch):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    patcher = KoboPatcher(make_device(tmp_path, source))
    replace = Path.replace

    def denied_replace(path, target):
        if path.name.startswith(".bookflow-") and path.name.endswith(".tmp"):
            raise PermissionError("read-only volume")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", denied_replace)
    with pytest.raises(PatchError, match="safely write"):
        patcher.patch("https://bookflow.example/api/kobo/abc")
    assert patcher.path.read_bytes() == source
    assert not list(patcher.path.parent.glob(".bookflow-*.tmp"))


def test_original_backup_is_not_overwritten_by_later_patch(tmp_path):
    source = b"[OneStoreServices]\napi_endpoint=https://before.example\n"
    patcher = KoboPatcher(make_device(tmp_path, source))
    patcher.patch("https://bookflow.example/api/kobo/first")
    patcher.patch("https://bookflow.example/api/kobo/second")
    assert patcher.original_backup_path.read_bytes() == source
