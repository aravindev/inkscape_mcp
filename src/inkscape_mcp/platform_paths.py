"""Where Inkscape keeps its extensions on Linux, macOS and Windows.

Pure path logic, no subprocess. Honours ``INKSCAPE_PROFILE_DIR`` (Inkscape's own override)
and derives the system data dir from the Inkscape binary when one is known, so relocated
and bundled installs (``Inkscape.app``, portable Windows builds) are found too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_profile_dir(platform: str | None = None) -> Path:
    """Inkscape's per-user profile dir (the parent of ``extensions/``)."""
    override = os.environ.get("INKSCAPE_PROFILE_DIR")
    if override:
        return Path(override).expanduser()
    platform = platform or sys.platform
    if platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return Path(appdata) / "inkscape"
    if platform == "darwin":
        return Path.home() / "Library/Application Support/org.inkscape.Inkscape/config/inkscape"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".config") / "inkscape"


def user_extensions_dir(platform: str | None = None) -> Path:
    return user_profile_dir(platform) / "extensions"


def system_extension_dirs(
    inkscape_binary: str | os.PathLike[str] | None = None, platform: str | None = None
) -> tuple[Path, ...]:
    """Candidate system-wide extension dirs for this platform, most specific first.

    Callers must tolerate dirs that do not exist.
    """
    platform = platform or sys.platform
    dirs: list[Path] = []

    if inkscape_binary:
        exe = Path(inkscape_binary)
        if exe.exists():
            exe = exe.resolve()
        if platform == "darwin":
            # .../Inkscape.app/Contents/MacOS/inkscape -> .../Contents/Resources/share/inkscape
            dirs.append(exe.parent.parent / "Resources/share/inkscape/extensions")
        elif platform == "win32":
            # ...\Inkscape\bin\inkscape.exe -> ...\Inkscape\share\inkscape
            dirs.append(exe.parent.parent / "share/inkscape/extensions")
        else:
            dirs.append(exe.parent.parent / "share/inkscape/extensions")

    if platform == "darwin":
        for app in (Path("/Applications/Inkscape.app"), Path.home() / "Applications/Inkscape.app"):
            dirs.append(app / "Contents/Resources/share/inkscape/extensions")
        dirs += [
            Path("/opt/homebrew/share/inkscape/extensions"),
            Path("/usr/local/share/inkscape/extensions"),
        ]
    elif platform == "win32":
        for var, default in (("ProgramFiles", r"C:\Program Files"), ("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            dirs.append(Path(os.environ.get(var, default)) / "Inkscape/share/inkscape/extensions")
    else:
        dirs += [
            Path("/usr/share/inkscape/extensions"),
            Path("/usr/local/share/inkscape/extensions"),
            Path("/snap/inkscape/current/share/inkscape/extensions"),
        ]

    return tuple(dict.fromkeys(dirs))  # de-duplicate, keeping order
