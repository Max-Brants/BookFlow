"""Archive extraction utilities for downloaded book archives."""

import stat
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Never, Protocol, Sequence, cast

from bookflow.core.logger import setup_logger
from bookflow.download.fs import atomic_move
from bookflow.download.postprocess.policy import get_supported_formats

logger = setup_logger(__name__)
_ARCHIVE_COPY_CHUNK_SIZE = 1024 * 1024
MAX_ARCHIVE_ENTRIES = 500
MAX_ARCHIVE_ENTRY_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 200
_FORBIDDEN_ARCHIVE_EXTENSIONS = frozenset(
    {".bat", ".cmd", ".com", ".exe", ".js", ".lnk", ".msi", ".ps1", ".scr", ".vbs"}
)

if TYPE_CHECKING:
    import rarfile

    ArchiveType = zipfile.ZipFile | rarfile.RarFile
else:
    ArchiveType = zipfile.ZipFile


def _delete_file_with_logging(file_path: Path, file_type_label: str, *, rejected: bool) -> None:
    """Delete a file and log the outcome."""
    try:
        file_path.unlink()
        if rejected:
            logger.debug("Deleted rejected %s file: %s", file_type_label, file_path.name)
        else:
            logger.debug("Deleted non-%s file: %s", file_type_label, file_path.name)
    except OSError as e:
        if rejected:
            logger.warning(
                "Failed to delete rejected %s file %s: %s", file_type_label, file_path, e
            )
        else:
            logger.warning("Failed to delete non-%s file %s: %s", file_type_label, file_path, e)


# Check for rarfile availability at module load
try:
    import rarfile

    RAR_AVAILABLE = True
except ImportError:
    RAR_AVAILABLE = False
    logger.warning("rarfile not installed - RAR extraction disabled")


class ArchiveExtractionError(Exception):
    """Raised when archive extraction fails."""


class PasswordProtectedError(ArchiveExtractionError):
    """Raised when archive requires a password."""


class CorruptedArchiveError(ArchiveExtractionError):
    """Raised when archive is corrupted."""


class ArchiveLimitError(ArchiveExtractionError):
    """Raised before or during extraction when resource limits are exceeded."""


def _raise_archive_limit(message: str) -> Never:
    raise ArchiveLimitError(message)


def is_archive(file_path: Path) -> bool:
    """Check if file is a supported archive format."""
    suffix = file_path.suffix.lower().lstrip(".")
    return suffix in ("zip", "rar")


def _is_supported_file(file_path: Path) -> bool:
    """Check if a file matches the configured ebook formats."""
    ext = file_path.suffix.lower().lstrip(".")
    return ext in get_supported_formats()


# All known ebook extensions (superset of what user might enable)
ALL_EBOOK_EXTENSIONS = {
    ".pdf",
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".fb2",
    ".djvu",
    ".cbz",
    ".cbr",
    ".doc",
    ".docx",
    ".rtf",
    ".txt",
}


def _filter_files(extracted_files: list[Path]) -> tuple[list[Path], list[Path], list[Path]]:
    """Filter extracted files into supported, disabled, and unrelated ebooks."""

    matched_files = []
    rejected_format_files = []
    other_files = []

    for file_path in extracted_files:
        if _is_supported_file(file_path):
            matched_files.append(file_path)
        elif file_path.suffix.lower() in ALL_EBOOK_EXTENSIONS:
            rejected_format_files.append(file_path)
        else:
            other_files.append(file_path)

    return matched_files, rejected_format_files, other_files


def extract_archive(
    archive_path: Path,
    output_dir: Path,
) -> tuple[list[Path], list[str], list[Path]]:
    """Extract archive and filter by content type. Returns (matched, warnings, rejected)."""
    suffix = archive_path.suffix.lower().lstrip(".")

    if suffix == "zip":
        extracted_files, warnings = _extract_zip(archive_path, output_dir)
    elif suffix == "rar":
        extracted_files, warnings = _extract_rar(archive_path, output_dir)
    else:
        msg = f"Unsupported archive format: {suffix}"
        raise ArchiveExtractionError(msg)

    file_type_label = "book"

    matched_files, rejected_files, other_files = _filter_files(extracted_files)

    # Delete rejected files (valid formats but not enabled by user)
    for rejected_file in rejected_files:
        _delete_file_with_logging(rejected_file, file_type_label, rejected=True)

    if rejected_files:
        rejected_exts = sorted({f.suffix.lower() for f in rejected_files})
        warnings.append(
            f"Skipped {len(rejected_files)} {file_type_label}(s) with unsupported format: {', '.join(rejected_exts)}"
        )

    # Delete other files (images, html, etc)
    for other_file in other_files:
        _delete_file_with_logging(other_file, file_type_label, rejected=False)

    if other_files:
        warnings.append(f"Skipped {len(other_files)} non-{file_type_label} file(s)")

    return matched_files, warnings, rejected_files


def extract_archive_raw(
    archive_path: Path,
    output_dir: Path,
) -> tuple[list[Path], list[str]]:
    """Extract archive without filtering (returns all extracted files)."""
    suffix = archive_path.suffix.lower().lstrip(".")

    if suffix == "zip":
        return _extract_zip(archive_path, output_dir)
    if suffix == "rar":
        return _extract_rar(archive_path, output_dir)

    msg = f"Unsupported archive format: {suffix}"
    raise ArchiveExtractionError(msg)


class _ArchiveMember(Protocol):
    filename: str

    def is_dir(self) -> bool: ...


def _validate_archive_members(infos: Sequence[_ArchiveMember]) -> None:
    """Reject bombs, executable payloads, and link-like members before extraction."""
    file_infos = [info for info in infos if not info.is_dir()]
    if len(file_infos) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveLimitError("Archive contains too many entries")

    total_size = 0
    for info in file_infos:
        filename = str(info.filename)
        if Path(filename).suffix.casefold() in _FORBIDDEN_ARCHIVE_EXTENSIONS:
            raise ArchiveExtractionError("Archive contains an executable payload")
        file_size = int(getattr(info, "file_size", 0) or 0)
        compressed_size = int(getattr(info, "compress_size", 0) or 0)
        if file_size < 0 or compressed_size < 0:
            raise ArchiveLimitError("Archive contains invalid member sizes")
        if file_size > MAX_ARCHIVE_ENTRY_BYTES:
            raise ArchiveLimitError("Archive member exceeds the size limit")
        total_size += file_size
        if total_size > MAX_ARCHIVE_TOTAL_BYTES:
            raise ArchiveLimitError("Archive exceeds the total extracted-size limit")
        if compressed_size == 0 and file_size > 0:
            raise ArchiveLimitError("Archive member has an unsafe compression ratio")
        if compressed_size and file_size / compressed_size > MAX_ARCHIVE_COMPRESSION_RATIO:
            raise ArchiveLimitError("Archive member has an unsafe compression ratio")

        external_attr = getattr(info, "external_attr", None)
        if isinstance(external_attr, int) and stat.S_ISLNK((external_attr >> 16) & 0xFFFF):
            raise ArchiveExtractionError("Archive contains a symbolic link")
        is_symlink = getattr(info, "is_symlink", None)
        if callable(is_symlink) and is_symlink():
            raise ArchiveExtractionError("Archive contains a symbolic link")


def _extract_files_from_archive(archive: ArchiveType, output_dir: Path) -> list[Path]:
    """Extract files from ZipFile or RarFile to output_dir with security checks."""
    extracted_files = []
    infos = list(archive.infolist())
    _validate_archive_members(infos)
    total_written = 0

    for info in infos:
        if info.is_dir():
            continue

        # Use only filename, strip directory path (security: prevent path traversal)
        filename = Path(info.filename).name
        if not filename:
            continue

        # Security: reject filenames with null bytes or path separators
        # Check both / and \ since archives may be created on different OSes
        if "\x00" in filename or "/" in filename or "\\" in filename:
            logger.warning("Skipping suspicious filename in archive: %r", info.filename)
            continue

        # Extract to output_dir with flat structure
        target_path = output_dir / filename

        # Security: verify resolved path stays within output directory (defense-in-depth)
        try:
            target_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            logger.warning("Path traversal attempt blocked: %r", info.filename)
            continue

        temp_path: Path | None = None
        try:
            with (
                archive.open(info) as src,
                tempfile.NamedTemporaryFile(
                    dir=output_dir,
                    prefix=".bookflow-extract-",
                    suffix=".tmp",
                    delete=False,
                ) as temp_file,
            ):
                temp_path = Path(temp_file.name)
                entry_written = 0
                while chunk := src.read(_ARCHIVE_COPY_CHUNK_SIZE):
                    entry_written += len(chunk)
                    total_written += len(chunk)
                    if entry_written > MAX_ARCHIVE_ENTRY_BYTES:
                        _raise_archive_limit("Archive member exceeds the size limit")
                    if total_written > MAX_ARCHIVE_TOTAL_BYTES:
                        _raise_archive_limit("Archive exceeds the total extracted-size limit")
                    temp_file.write(chunk)

            final_path = atomic_move(cast("Path", temp_path), target_path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise
        extracted_files.append(final_path)
        logger.debug("Extracted: %s", filename)

    return extracted_files


def _extract_zip(archive_path: Path, output_dir: Path) -> tuple[list[Path], list[str]]:
    """Extract files from a ZIP archive."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            # Check for password protection
            for info in zf.infolist():
                if info.flag_bits & 0x1:  # Encrypted flag
                    msg = "ZIP archive is password protected"
                    raise PasswordProtectedError(msg)

            # Test archive integrity
            bad_file = zf.testzip()
            if bad_file:
                msg = f"Corrupted file in archive: {bad_file}"
                raise CorruptedArchiveError(msg)

            return _extract_files_from_archive(zf, output_dir), []

    except zipfile.BadZipFile as e:
        msg = f"Invalid or corrupted ZIP: {e}"
        raise CorruptedArchiveError(msg) from e
    except PermissionError as e:
        msg = f"Permission denied: {e}"
        raise ArchiveExtractionError(msg) from e


def _extract_rar(archive_path: Path, output_dir: Path) -> tuple[list[Path], list[str]]:
    """Extract files from a RAR archive."""
    if not RAR_AVAILABLE:
        msg = "RAR extraction not available - rarfile library not installed"
        raise ArchiveExtractionError(msg)

    try:
        with rarfile.RarFile(archive_path, "r") as rf:
            # Check for password protection
            if rf.needs_password():
                msg = "RAR archive is password protected"
                raise PasswordProtectedError(msg)

            # Test archive integrity
            rf.testrar()

            return _extract_files_from_archive(rf, output_dir), []

    except rarfile.BadRarFile as e:
        msg = f"Invalid or corrupted RAR: {e}"
        raise CorruptedArchiveError(msg) from e
    except rarfile.RarCannotExec as e:
        msg = "unrar binary not found - install unrar package"
        raise ArchiveExtractionError(msg) from e
    except PermissionError as e:
        msg = f"Permission denied: {e}"
        raise ArchiveExtractionError(msg) from e
