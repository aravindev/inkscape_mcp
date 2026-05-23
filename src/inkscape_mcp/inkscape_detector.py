"""Inkscape executable detection."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Fallbacks if `inkscape` is not on $PATH.
_FALLBACK_PATHS: tuple[Path, ...] = (
    Path("/usr/bin/inkscape"),
    Path("/usr/local/bin/inkscape"),
    Path("/snap/bin/inkscape"),
    Path("/var/lib/flatpak/exports/bin/org.inkscape.Inkscape"),
    Path("~/.local/bin/inkscape").expanduser(),
)


class InkscapeDetector:
    """Find the Inkscape executable on Linux."""

    def detect_inkscape_installation(self) -> str | None:
        """Return the path to a usable `inkscape` binary, or None."""
        on_path = shutil.which("inkscape")
        if on_path:
            return on_path

        for candidate in _FALLBACK_PATHS:
            if candidate.is_file() and self._is_executable(candidate):
                return str(candidate)

        logger.warning("Inkscape not found on $PATH or any known fallback location")
        return None

    @staticmethod
    def _is_executable(path: Path) -> bool:
        import os

        return os.access(path, os.X_OK)
