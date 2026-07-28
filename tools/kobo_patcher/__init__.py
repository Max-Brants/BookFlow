"""BookFlow's standalone, Windows-focused Kobo configuration patcher."""

from .service import KoboPatcher, PatchResult

__all__ = ["KoboPatcher", "PatchResult"]
