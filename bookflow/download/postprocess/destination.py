"""Destination planning helpers for post-processing outputs."""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from bookflow.core.logger import setup_logger
from bookflow.core.utils import (
    get_destination,
)
from bookflow.download.fs import run_blocking_io
from bookflow.download.permissions_debug import log_path_permission_context
from bookflow.release_sources import get_source

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from bookflow.core.models import DownloadTask

logger = setup_logger("bookflow.download.postprocess.pipeline")


def validate_destination(
    destination: Path, status_callback: Callable[[str, str | None], None]
) -> bool:
    """Validate destination path is absolute, exists, and writable."""
    if not destination.is_absolute():
        logger.warning("Destination must be absolute: %s", destination)
        status_callback("error", f"Destination must be absolute: {destination}")
        return False

    destination_exists = run_blocking_io(destination.exists)
    if destination_exists and not run_blocking_io(destination.is_dir):
        logger.warning("Destination is not a directory: %s", destination)
        status_callback("error", f"Destination is not a directory: {destination}")
        return False

    created_by_us = False
    if not destination_exists:
        try:
            run_blocking_io(destination.mkdir, parents=True, exist_ok=True)
            created_by_us = True
        except (OSError, PermissionError) as exc:
            log_path_permission_context("destination_create", destination)
            logger.warning("Cannot create destination: %s (%s)", destination, exc)
            status_callback("error", f"Cannot create destination: {destination} ({exc})")
            return False

    test_path = destination / f".bookflow_write_test_{uuid.uuid4().hex}.tmp"

    try:
        test_content = (
            f"This file was created to verify if '{destination}' is writable. "
            "It should've been automatically deleted. Feel free to delete it.\n"
        )
        run_blocking_io(test_path.write_text, test_content)
        run_blocking_io(test_path.unlink, missing_ok=True)
    except OSError as exc:
        logger.debug("Destination write probe path: %s", test_path)
        log_path_permission_context("destination_write_probe", destination)
        logger.warning("Destination not writable: %s (%s)", destination, exc)
        status_callback("error", f"Destination not writable: {destination} ({exc})")
        if created_by_us:
            with contextlib.suppress(OSError):
                run_blocking_io(destination.rmdir)
        return False

    return True


def get_final_destination(task: DownloadTask) -> Path:
    """Get final ebook destination directory, with source routing support."""

    try:
        override = get_source(task.source).get_destination_override(task)
    except ValueError:
        override = None

    if override:
        return override

    return get_destination()
