"""Persistent named release profiles and deterministic request_process snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Any

from bookflow.core.release_candidates import ReleaseProfile

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_PROFILE_CONFIG: dict[str, Any] = {
    "allowed_formats": ["epub"],
    "allowed_protocols": ["torrent", "usenet", "direct"],
    "allowed_languages": [],
    "allowed_indexers": [],
    "max_size_bytes": None,
    "min_seeders": 0,
    "allow_bundles": False,
    "allow_archives": False,
    "positive_terms": [],
    "negative_terms": [],
    "indexer_priorities": {},
    "score_weights": {},
    "term_scores": {},
    "minimum_automatic_score": 0,
}


class ReleaseProfileError(ValueError):
    """A profile cannot be used or persisted."""


def canonical_profile_config(value: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize public profile configuration into safe JSON primitives."""
    if value is not None and not isinstance(value, dict):
        raise ReleaseProfileError("profile config must be an object")
    result = dict(DEFAULT_PROFILE_CONFIG)
    result.update(value or {})
    for key in (
        "allowed_formats",
        "allowed_protocols",
        "allowed_indexers",
        "allowed_languages",
        "positive_terms",
        "negative_terms",
    ):
        raw = result.get(key, [])
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ReleaseProfileError(f"{key} must be a list of strings")
        result[key] = [item.strip() for item in raw if item.strip()]
    if not isinstance(result.get("indexer_priorities"), dict):
        raise ReleaseProfileError("indexer_priorities must be an object")
    result["indexer_priorities"] = {
        str(key): int(score) for key, score in result["indexer_priorities"].items()
    }
    if not isinstance(result.get("score_weights"), dict) or not isinstance(
        result.get("term_scores"), dict
    ):
        raise ReleaseProfileError("score_weights and term_scores must be objects")
    result["score_weights"] = {
        str(key): int(score) for key, score in result["score_weights"].items()
    }
    result["term_scores"] = {str(key): int(score) for key, score in result["term_scores"].items()}
    for key in ("min_seeders", "minimum_automatic_score"):
        if isinstance(result.get(key), bool):
            raise ReleaseProfileError(f"{key} must be an integer")
        result[key] = int(result.get(key, 0))
    if result["min_seeders"] < 0:
        raise ReleaseProfileError("min_seeders cannot be negative")
    max_size = result.get("max_size_bytes")
    if max_size is not None:
        if isinstance(max_size, bool) or int(max_size) < 0:
            raise ReleaseProfileError("max_size_bytes must be a non-negative integer or null")
        result["max_size_bytes"] = int(max_size)
    for key in ("allow_bundles", "allow_archives"):
        if not isinstance(result.get(key), bool):
            raise ReleaseProfileError(f"{key} must be a boolean")
    return result


def profile_snapshot_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    config = canonical_profile_config(json.loads(str(row["config_json"])))
    return {"profile_id": int(row["id"]), "profile_name": str(row["name"]), **config}


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def release_profile_from_snapshot(
    snapshot: dict[str, Any],
    *,
    title: str,
    author: str | None,
    language: str | None,
    publish_year: int | None,
    isbn: str | None = None,
) -> ReleaseProfile:
    return ReleaseProfile(
        title=title,
        authors=(author,) if author else (),
        isbn=isbn,
        language=language,
        publish_year=publish_year,
        allowed_formats=tuple(snapshot.get("allowed_formats") or ("epub",)),
        allowed_protocols=tuple(
            snapshot.get("allowed_protocols") or ("direct", "torrent", "usenet")
        ),
        allowed_indexers=tuple(snapshot.get("allowed_indexers") or ()),
        allowed_languages=tuple(snapshot.get("allowed_languages") or ()),
        max_size_bytes=snapshot.get("max_size_bytes"),
        min_seeders=int(snapshot.get("min_seeders", 0)),
        positive_terms=tuple(snapshot.get("positive_terms") or ()),
        negative_terms=tuple(snapshot.get("negative_terms") or ()),
        allow_bundles=bool(snapshot.get("allow_bundles", False)),
        allow_archives=bool(snapshot.get("allow_archives", False)),
        indexer_priorities=dict(snapshot.get("indexer_priorities") or {}),
        score_weights=dict(snapshot.get("score_weights") or {}),
        term_scores=dict(snapshot.get("term_scores") or {}),
        minimum_automatic_score=int(snapshot.get("minimum_automatic_score", 0)),
    )


class ReleaseProfileService:
    def __init__(self, database_path: str | Path) -> None:
        self._db_path = str(database_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["config"] = canonical_profile_config(json.loads(str(value.pop("config_json"))))
        value["is_default"] = bool(value["is_default"])
        value["is_active"] = bool(value["is_active"])
        return value

    def list(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            sql = "SELECT * FROM release_profiles"
            if active_only:
                sql += " WHERE is_active = 1"
            return [
                self._serialize(row)
                for row in conn.execute(sql + " ORDER BY is_default DESC, name COLLATE NOCASE")
            ]

    def get(self, profile_id: int, *, active_only: bool = False) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM release_profiles WHERE id = ? AND is_active = 1"
                if active_only
                else "SELECT * FROM release_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise ReleaseProfileError("Release profile not found")
        return row

    def create(
        self,
        *,
        name: str,
        config: dict[str, Any] | None,
        is_default: bool = False,
        is_active: bool = True,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ReleaseProfileError("name is required")
        if is_default and not is_active:
            raise ReleaseProfileError("The default release profile must stay active")
        encoded = json.dumps(
            canonical_profile_config(config), sort_keys=True, separators=(",", ":")
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                is_default
                or conn.execute("SELECT 1 FROM release_profiles WHERE is_default = 1").fetchone()
                is None
            ):
                conn.execute("UPDATE release_profiles SET is_default = 0 WHERE is_default = 1")
                is_default = True
                is_active = True
            cursor = conn.execute(
                "INSERT INTO release_profiles (name, config_json, is_default, is_active, created_by) VALUES (?, ?, ?, ?, ?)",
                (normalized_name, encoded, int(is_default), int(is_active), created_by),
            )
            row = conn.execute(
                "SELECT * FROM release_profiles WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            conn.commit()
        return self._serialize(row)

    def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        is_default: bool | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM release_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if row is None:
                raise ReleaseProfileError("Release profile not found")
            next_name = name.strip() if isinstance(name, str) else str(row["name"])
            if not next_name:
                raise ReleaseProfileError("name is required")
            next_config = (
                canonical_profile_config(config)
                if config is not None
                else canonical_profile_config(json.loads(str(row["config_json"])))
            )
            next_default = bool(row["is_default"]) if is_default is None else is_default
            next_active = bool(row["is_active"]) if is_active is None else is_active
            if not next_active and next_default:
                raise ReleaseProfileError("The default release profile must stay active")
            if next_default:
                conn.execute(
                    "UPDATE release_profiles SET is_default = 0 WHERE id <> ?", (profile_id,)
                )
            conn.execute(
                "UPDATE release_profiles SET name=?, config_json=?, is_default=?, is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    next_name,
                    json.dumps(next_config, sort_keys=True, separators=(",", ":")),
                    int(next_default),
                    int(next_active),
                    profile_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM release_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            conn.commit()
        return self._serialize(row)

    def delete(self, profile_id: int) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT is_default FROM release_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if row is None:
                raise ReleaseProfileError("Release profile not found")
            if row["is_default"]:
                raise ReleaseProfileError("The default release profile cannot be deleted")
            conn.execute("DELETE FROM release_profiles WHERE id=?", (profile_id,))
            conn.commit()
