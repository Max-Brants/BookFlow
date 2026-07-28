"""A deliberately small, line-preserving editor for Kobo eReader.conf files."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass

OFFICIAL_KOBO_ENDPOINT = "https://storeapi.kobo.com"

_SECTION = re.compile(r"^\s*\[\s*([^]\r\n]+?)\s*\]\s*(?:[;#].*)?$")
_ENDPOINT = re.compile(r"^(\s*api_endpoint\s*=\s*)(.*?)(\s*(?:[;#].*)?)$")


class ConfError(ValueError):
    """The config is ambiguous or cannot be safely edited."""


@dataclass(frozen=True)
class TextEncoding:
    encoding: str
    bom: bytes


def _detect_encoding(raw: bytes) -> TextEncoding:
    if raw.startswith(codecs.BOM_UTF8):
        return TextEncoding("utf-8", codecs.BOM_UTF8)
    if raw.startswith(codecs.BOM_UTF16_LE):
        return TextEncoding("utf-16-le", codecs.BOM_UTF16_LE)
    if raw.startswith(codecs.BOM_UTF16_BE):
        return TextEncoding("utf-16-be", codecs.BOM_UTF16_BE)
    # Kobo configuration files are UTF-8. Rejecting malformed data is safer than
    # guessing a legacy code page and damaging an e-reader config.
    return TextEncoding("utf-8", b"")


class KoboConf:
    """Editable config retaining all untouched bytes and line endings verbatim."""

    def __init__(self, raw: bytes) -> None:
        self._encoding = _detect_encoding(raw)
        body = raw[len(self._encoding.bom) :]
        try:
            self._text = body.decode(self._encoding.encoding)
        except UnicodeDecodeError as exc:
            raise ConfError("Kobo eReader.conf is not valid UTF-8/UTF-16 text") from exc
        self._lines = self._text.splitlines(keepends=True)
        if self._text and not self._lines:
            self._lines = [self._text]

    @classmethod
    def from_bytes(cls, raw: bytes) -> KoboConf:
        return cls(raw)

    def to_bytes(self) -> bytes:
        return self._encoding.bom + "".join(self._lines).encode(self._encoding.encoding)

    def _newline(self) -> str:
        for line in self._lines:
            if line.endswith("\r\n"):
                return "\r\n"
            if line.endswith("\n"):
                return "\n"
            if line.endswith("\r"):
                return "\r"
        return "\r\n"

    @staticmethod
    def _without_newline(line: str) -> tuple[str, str]:
        if line.endswith("\r\n"):
            return line[:-2], "\r\n"
        if line.endswith(("\n", "\r")):
            return line[:-1], line[-1:]
        return line, ""

    def _sections(self) -> list[tuple[int, int]]:
        sections: list[tuple[int, int]] = []
        for index, line in enumerate(self._lines):
            body, _ = self._without_newline(line)
            match = _SECTION.match(body)
            if match and match.group(1).strip().casefold() == "onestoreservices":
                sections.append((index, -1))
        if len(sections) > 1:
            raise ConfError("Multiple [OneStoreServices] sections found; refusing to guess")
        if not sections:
            return []
        start = sections[0][0]
        end = len(self._lines)
        for index in range(start + 1, len(self._lines)):
            body, _ = self._without_newline(self._lines[index])
            if _SECTION.match(body):
                end = index
                break
        return [(start, end)]

    def endpoint(self) -> str | None:
        sections = self._sections()
        if not sections:
            return None
        _, end = sections[0]
        start = sections[0][0]
        matches: list[str] = []
        for line in self._lines[start + 1 : end]:
            body, _ = self._without_newline(line)
            match = _ENDPOINT.match(body)
            if match:
                matches.append(match.group(2).strip())
        if len(matches) > 1:
            raise ConfError("Multiple active api_endpoint values found; refusing to guess")
        return matches[0] if matches else None

    def set_endpoint(self, endpoint: str, *, create_section: bool = True) -> None:
        if not endpoint or "\r" in endpoint or "\n" in endpoint:
            raise ConfError("Endpoint must be one non-empty line")
        sections = self._sections()
        newline = self._newline()
        if not sections:
            if not create_section:
                raise ConfError("[OneStoreServices] is missing")
            if self._lines and not self._lines[-1].endswith(("\n", "\r")):
                self._lines[-1] += newline
            self._lines.extend(
                [f"[OneStoreServices]{newline}", f"api_endpoint={endpoint}{newline}"]
            )
            return

        start, end = sections[0]
        matches: list[int] = []
        for index in range(start + 1, end):
            body, _ = self._without_newline(self._lines[index])
            if _ENDPOINT.match(body):
                matches.append(index)
        if len(matches) > 1:
            raise ConfError("Multiple active api_endpoint values found; refusing to guess")
        if matches:
            index = matches[0]
            body, ending = self._without_newline(self._lines[index])
            match = _ENDPOINT.match(body)
            if match is None:
                raise ConfError("Could not safely parse api_endpoint")
            self._lines[index] = f"{match.group(1)}{endpoint}{match.group(3)}{ending}"
            return
        self._lines.insert(end, f"api_endpoint={endpoint}{newline}")

    def has_usable_structure(self) -> bool:
        """Require a basic, unambiguous INI document before restoring a full backup."""
        if not self._text.strip() or self._has_duplicate_target_section():
            return False
        section_count = 0
        for line in self._lines:
            body, _ = self._without_newline(line)
            stripped = body.strip()
            if not stripped or stripped.startswith((";", "#")):
                continue
            if _SECTION.match(body):
                section_count += 1
                continue
            if "=" not in body:
                return False
        return section_count > 0

    def _has_duplicate_target_section(self) -> bool:
        try:
            self._sections()
        except ConfError:
            return True
        return False
