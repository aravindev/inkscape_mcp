"""Inkscape executable detection."""

from __future__ import annotations

import logging

from . import platform_support

logger = logging.getLogger(__name__)


class InkscapeDetector:
    """Find the Inkscape executable on Linux, macOS, or Windows."""

    def detect_inkscape_installation(self) -> str | None:
        """Return the path to a usable `inkscape` binary, or None."""
        detected = platform_support.resolve_inkscape_binary()
        if detected:
            return detected

        if platform_support.is_macos():
            logger.warning(
                "Inkscape not found. Install Inkscape.app into /Applications, or set "
                "INKSCAPE_BIN=/Applications/Inkscape.app/Contents/MacOS/inkscape"
            )
        else:
            logger.warning("Inkscape not found on $PATH or any known fallback location")
        return None
