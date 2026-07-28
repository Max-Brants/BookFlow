"""Canonical filesystem guards for file serving and client-data cleanup.

The helpers in this module deliberately *validate* a path rather than deleting
or opening it.  Their callers must use the returned canonical path immediately
and must not derive a parent directory from it.  This keeps the policy usable
at two sensitive boundaries without coupling it to a particular download
client or Flask route.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

type PathInput = str | os.PathLike[str]


class PathSecurityError(ValueError):
    """Raised when a filesystem path does not meet the containment policy."""


def _has_parent_reference(path: Path) -> bool:
    """Return whether the submitted spelling contains a traversal component."""
    return ".." in path.parts


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or detectable Windows reparse point.

    ``Path.is_symlink`` covers normal symbolic links.  Windows junctions and
    other reparse points are not consistently reported as symlinks, but Python
    exposes the reparse attribute through ``st_file_attributes`` on Windows.
    The attribute is absent on POSIX, where this conservatively returns False.
    """
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise PathSecurityError(f"Cannot inspect path: {path}") from exc

    if stat.S_ISLNK(path_stat.st_mode):
        return True

    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(attributes & reparse_flag)


def _reject_reparse_components(path: Path) -> None:
    """Reject any symlink or reparse point in an absolute submitted path."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if _is_reparse_point(current):
            raise PathSecurityError(f"Path contains a symlink or reparse point: {current}")


def _resolve_allowed_root(root: PathInput) -> Path:
    submitted_root = Path(root)
    if not submitted_root.is_absolute():
        raise PathSecurityError(f"Allowed root must be absolute: {submitted_root}")
    if _has_parent_reference(submitted_root):
        raise PathSecurityError(f"Allowed root cannot contain traversal: {submitted_root}")
    _reject_reparse_components(submitted_root)

    try:
        resolved_root = submitted_root.resolve(strict=True)
    except OSError as exc:
        raise PathSecurityError(f"Allowed root does not exist: {submitted_root}") from exc
    if not resolved_root.is_dir():
        raise PathSecurityError(f"Allowed root is not a directory: {submitted_root}")
    return resolved_root


def resolve_allowed_directory(root: PathInput) -> Path:
    """Return a canonical configured root after rejecting reparse components."""
    return _resolve_allowed_root(root)


def _require_contained_existing_path(path: PathInput, allowed_roots: tuple[PathInput, ...]) -> Path:
    """Resolve an existing non-reparse path strictly below one configured root."""
    if not allowed_roots:
        raise PathSecurityError("At least one allowed root is required")

    submitted_path = Path(path)
    if not submitted_path.is_absolute():
        raise PathSecurityError(f"Path must be absolute: {submitted_path}")
    if _has_parent_reference(submitted_path):
        raise PathSecurityError(f"Path cannot contain traversal: {submitted_path}")
    _reject_reparse_components(submitted_path)

    resolved_roots = tuple(_resolve_allowed_root(root) for root in allowed_roots)
    try:
        resolved_path = submitted_path.resolve(strict=True)
    except OSError as exc:
        raise PathSecurityError(f"Path does not exist: {submitted_path}") from exc

    containing_root: Path | None = None
    for root in resolved_roots:
        try:
            resolved_path.relative_to(root)
        except ValueError:
            continue
        containing_root = root
        break
    if containing_root is None or resolved_path == containing_root:
        raise PathSecurityError(f"Path must be strictly below an allowed root: {submitted_path}")

    return resolved_path


def resolve_library_file(path: PathInput, *, allowed_roots: tuple[PathInput, ...]) -> Path:
    """Return a canonical existing regular file below an approved library root.

    Directories, missing paths, roots themselves, symlinks and detectable
    junction/reparse paths are rejected.  Callers should revalidate immediately
    before opening the returned path to limit time-of-check/time-of-use races.
    """
    resolved_path = _require_contained_existing_path(path, allowed_roots)
    if not resolved_path.is_file():
        raise PathSecurityError(f"Library path is not a regular file: {resolved_path}")
    return resolved_path


def resolve_client_job_cleanup_leaf(claimed_path: PathInput, *, client_root: PathInput) -> Path:
    """Return one exact existing client job leaf that may be cleaned up.

    A cleanup caller may delete only this returned path, never ``client_root``
    or a parent derived from it.  A job leaf can be a regular file or a
    directory because download clients commonly report either shape.
    """
    return _require_contained_existing_path(claimed_path, (client_root,))
