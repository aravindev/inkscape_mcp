"""Inkscape executable detection (Linux, macOS, Windows)."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _fallback_paths(platform: str | None = None) -> tuple[Path, ...]:
    """Well-known install locations to try when `inkscape` is not on $PATH."""
    platform = platform or sys.platform
    home = Path.home()

    if platform == "darwin":
        return (
            Path("/Applications/Inkscape.app/Contents/MacOS/inkscape"),
            home / "Applications/Inkscape.app/Contents/MacOS/inkscape",
            Path("/opt/homebrew/bin/inkscape"),  # Apple Silicon Homebrew
            Path("/usr/local/bin/inkscape"),  # Intel Homebrew
        )

    if platform == "win32":
        roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")), "Programs"),
        ]
        # inkscape.com is the console build (stdout works); inkscape.exe is the GUI build.
        names = ("inkscape.com", "inkscape.exe")
        return tuple(Path(root) / "Inkscape" / "bin" / name for root in roots for name in names)

    return (
        Path("/usr/bin/inkscape"),
        Path("/usr/local/bin/inkscape"),
        Path("/snap/bin/inkscape"),
        Path("/var/lib/flatpak/exports/bin/org.inkscape.Inkscape"),
        home / ".local/bin/inkscape",
    )


class InkscapeDetector:
    """Find the Inkscape executable on Linux, macOS or Windows."""

    def detect_inkscape_installation(self) -> str | None:
        """Return the path to a usable `inkscape` binary, or None."""
        on_path = shutil.which("inkscape")
        if on_path:
            return on_path

        for candidate in _fallback_paths():
            if candidate.is_file() and self._is_executable(candidate):
                return str(candidate)

        logger.warning("Inkscape not found on $PATH or any known fallback location")
        return None

    @staticmethod
    def _is_executable(path: Path) -> bool:
        return os.access(path, os.X_OK)
