"""Platform-specific discovery for Inkscape paths and executables.

Inkscape lays out its installation and user profile differently on macOS than on
Linux. The macOS app is a bundle, so the executable is not on ``$PATH``, system
extensions live inside the bundle, and GLib resolves the user config directory
to ``~/Library/Application Support`` rather than ``~/.config``.

Everything platform-dependent that the rest of the server needs is centralised
here so the Linux/Windows code paths stay untouched.
"""

from __future__ import annotations

import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MACOS_APP_NAME = "Inkscape.app"
_BUNDLE_BINARY = Path("Contents/MacOS/inkscape")
_BUNDLE_BIN_DIR = Path("Contents/Resources/bin")
_BUNDLE_EXTENSIONS = Path("Contents/Resources/share/inkscape/extensions")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def macos_app_candidates() -> list[Path]:
    """Plausible locations of Inkscape.app on macOS, in priority order."""
    candidates: list[Path] = []
    override = os.environ.get("INKSCAPE_APP")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend(
        [
            Path("/Applications") / MACOS_APP_NAME,
            Path.home() / "Applications" / MACOS_APP_NAME,
        ]
    )
    return candidates


def find_macos_app() -> Path | None:
    """Return the first existing Inkscape.app bundle, or None."""
    for candidate in macos_app_candidates():
        if (candidate / _BUNDLE_BINARY).is_file():
            return candidate
    return None


def macos_app_for_binary(binary: str | Path) -> Path | None:
    """Return the bundle containing ``binary`` when it is inside Inkscape.app."""
    path = Path(binary).expanduser()
    for parent in path.parents:
        if parent.suffix == ".app" and (parent / _BUNDLE_BINARY).resolve() == path.resolve():
            return parent
    return None


def macos_inkscape_binary() -> str | None:
    """Path to the macOS bundle executable, if Inkscape.app is installed."""
    app = find_macos_app()
    if app is None:
        return None
    return str(app / _BUNDLE_BINARY)


def inkscape_binary_candidates() -> list[Path]:
    """Known Inkscape executable locations for the current platform."""
    if is_macos():
        app = find_macos_app()
        if app is not None:
            return [app / _BUNDLE_BINARY]
        return [candidate / _BUNDLE_BINARY for candidate in macos_app_candidates()]

    return [
        Path("/usr/bin/inkscape"),
        Path("/usr/local/bin/inkscape"),
        Path("/snap/bin/inkscape"),
        Path("/var/lib/flatpak/exports/bin/org.inkscape.Inkscape"),
        Path("~/.local/bin/inkscape").expanduser(),
    ]


def resolve_inkscape_binary() -> str | None:
    """Find a runnable Inkscape binary: ``$PATH`` first, then known locations."""
    on_path = shutil.which("inkscape")
    if on_path:
        return on_path
    for candidate in inkscape_binary_candidates():
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


def profile_dir() -> Path:
    """Inkscape's per-user profile directory.

    Inkscape honours ``INKSCAPE_PROFILE_DIR``; on macOS the GTK build maps the
    GLib config directory to ``~/Library/Application Support``.
    """
    override = os.environ.get("INKSCAPE_PROFILE_DIR")
    if override:
        return Path(override).expanduser()

    if is_windows():
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return Path(appdata) / "inkscape"

    if is_macos():
        return Path.home() / "Library" / "Application Support" / "org.inkscape.Inkscape" / "config" / "inkscape"

    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "inkscape"


def live_profile_dir() -> Path:
    """Keep the managed macOS instance separate from the user's normal profile."""
    if is_macos():
        return Path.home() / ".cache" / "inkscape_mcp" / "inkscape-profile"
    return profile_dir()


def user_extensions_dir() -> Path:
    return profile_dir() / "extensions"


def system_extensions_dirs() -> tuple[Path, ...]:
    """Directories holding Inkscape's bundled extensions."""
    dirs: list[Path] = []
    if is_macos():
        for app in [find_macos_app(), *macos_app_candidates()]:
            if app is not None and (app / _BUNDLE_EXTENSIONS).is_dir():
                dirs.append(app / _BUNDLE_EXTENSIONS)
                break
        # Homebrew / manual builds that install the share tree outside the bundle.
        dirs.extend(
            [
                Path("/opt/homebrew/share/inkscape/extensions"),
                Path("/usr/local/share/inkscape/extensions"),
            ]
        )
    else:
        dirs.extend([Path("/usr/share/inkscape/extensions"), Path("/usr/local/share/inkscape/extensions")])
    # Preserve order while dropping duplicates.
    return tuple(dict.fromkeys(dirs))


def bundled_python(inkscape_binary: str | None = None) -> str | None:
    """Inkscape's own bundled Python interpreter, reported by diagnostics.

    Some installations have stalled in its ``dyld_start``. The managed instance
    therefore uses the MCP interpreter instead (see
    ``extension_interpreter`` and ``set_inkscape_python_preference``).
    """
    if not is_macos():
        return None

    binaries = []
    if inkscape_binary:
        binaries.append(Path(inkscape_binary))
    app = find_macos_app()
    if app is not None:
        binaries.append(app / _BUNDLE_BINARY)

    for binary in binaries:
        app_dir = macos_app_for_binary(binary)
        if app_dir is None:
            continue
        candidate = app_dir / _BUNDLE_BIN_DIR / "python3"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def extension_interpreter(declared: str | None) -> str:
    """Resolve an INX interpreter declaration to a usable executable.

    Headless execution is done by the MCP itself, so it uses the MCP's own Python
    (which has inkex installed). Inkscape's bundled interpreter is only relevant
    for extensions Inkscape runs itself.
    """
    declared = (declared or "").strip()
    if is_macos() and declared in {"", "python", "python3", "python3.10", "python3.11", "python3.12"}:
        return sys.executable
    if declared in {"", "python"}:
        return sys.executable
    return declared


def _preferences_path() -> Path:
    return live_profile_dir() / "preferences.xml"


def set_inkscape_python_preference(interpreter: str | None = None) -> dict[str, Any]:
    """Configure extension Python only in the MCP-owned macOS live profile.

    Some macOS installations have stalled in the bundled Python's ``dyld_start``.
    This workaround is deliberately scoped to the managed instance, and is applied
    before launch rather than during headless server initialization. No normal user
    preferences are changed or require restoration on uninstall.
    """
    if not is_macos():
        return {"changed": False, "reason": "macOS only"}

    if os.environ.get("INKSCAPE_MCP_SET_PYTHON_PREF") == "0":
        return {"changed": False, "reason": "disabled via INKSCAPE_MCP_SET_PYTHON_PREF=0"}

    target = interpreter or sys.executable
    prefs = _preferences_path()

    try:
        if prefs.exists():
            tree = ET.parse(prefs)  # noqa: S314 — local Inkscape preferences file
            root = tree.getroot()
        else:
            prefs.parent.mkdir(parents=True, exist_ok=True)
            root = ET.Element("inkscape", {"version": "1"})
            tree = ET.ElementTree(root)

        group = next((node for node in root.findall("group") if node.get("id") == "extensions"), None)
        if group is None:
            group = ET.SubElement(root, "group", {"id": "extensions"})

        previous = group.get("python-interpreter")
        if previous == target:
            return {"changed": False, "value": target, "previous": previous}

        group.set("python-interpreter", target)
        tmp = prefs.with_suffix(".xml.mcp-tmp")
        tree.write(tmp, encoding="UTF-8", xml_declaration=True)
        tmp.replace(prefs)
        return {"changed": True, "value": target, "previous": previous}
    except Exception as exc:
        # Best-effort: live support degrades, headless still works.
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}", "path": str(prefs)}


def python_preference_status() -> dict[str, Any]:
    """Report the effective Inkscape interpreter preference (for diagnostics)."""
    if not is_macos():
        return {"supported": False}
    prefs = _preferences_path()
    status: dict[str, Any] = {"supported": True, "path": str(prefs), "exists": prefs.exists()}
    try:
        root = ET.parse(prefs).getroot()  # noqa: S314 — local Inkscape preferences file
        group = next((node for node in root.findall("group") if node.get("id") == "extensions"), None)
        status["python_interpreter"] = group.get("python-interpreter") if group is not None else None
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status
