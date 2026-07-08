"""Windows session-bus + Inkscape auto-manager for the live bridge.

On Windows there is no autostarted D-Bus session bus, and a normally-launched Inkscape
is not reachable for live control. This module makes the live bridge "just work" by:

  1. ensuring a private ``dbus-daemon`` session bus is running (reused across MCP
     restarts via a state file), and
  2. ensuring Inkscape is running *under that bus* (launched with
     ``DBUS_SESSION_BUS_ADDRESS`` set), so its ``org.gtk.Actions`` surface is exported.

Everything here is best-effort and lazy: nothing is spawned until a live operation needs
it. Linux/macOS keep using the jeepney path and never touch this module.

Discovery / overrides (env):
  INKSCAPE_MCP_DBUS_DAEMON   full path to dbus-daemon.exe
  INKSCAPE_MCP_GDBUS         full path to gdbus.exe
  INKS_INKSCAPE_BIN / INKSCAPE_BIN   inkscape.exe (already used elsewhere)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

STATE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp"))
ADDRESS_FILE = STATE_DIR / "bus_address"

# Where MSYS2 puts dbus-daemon; used if not overridden and not on PATH.
_DEFAULT_DBUS_DAEMONS = (
    r"C:\msys64\mingw64\bin\dbus-daemon.exe",
    r"C:\msys64\ucrt64\bin\dbus-daemon.exe",
)

_INKSCAPE_REGISTER_TIMEOUT_S = 25.0
_BUS_PRINT_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.3

# Detached, no console window — survives MCP-server restarts.
_DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


class BusError(RuntimeError):
    pass


# ---- discovery ---------------------------------------------------------------------


def find_dbus_daemon() -> str | None:
    override = os.environ.get("INKSCAPE_MCP_DBUS_DAEMON")
    if override and Path(override).exists():
        return override
    from shutil import which

    found = which("dbus-daemon")
    if found:
        return found
    for cand in _DEFAULT_DBUS_DAEMONS:
        if Path(cand).exists():
            return cand
    return None


def find_gdbus(inkscape_executable: str | None = None) -> str | None:
    override = os.environ.get("INKSCAPE_MCP_GDBUS")
    if override and Path(override).exists():
        return override
    # gdbus.exe ships next to inkscape.exe.
    if inkscape_executable:
        cand = Path(inkscape_executable).with_name("gdbus.exe")
        if cand.exists():
            return str(cand)
    from shutil import which

    return which("gdbus")


# ---- bus lifecycle -----------------------------------------------------------------


def _bus_reachable(gdbus_path: str, address: str) -> bool:
    """True if a dbus-daemon is answering at ``address`` (independent of Inkscape)."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed gdbus path
            [
                gdbus_path,
                "call",
                "--address",
                address,
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.GetId",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def ensure_bus(gdbus_path: str) -> str:
    """Return a reachable session-bus address, reusing or starting a dbus-daemon.

    The address is cached in ``ADDRESS_FILE`` so repeated MCP-server starts reuse one
    daemon instead of leaking a new one each time.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if ADDRESS_FILE.exists():
        cached = ADDRESS_FILE.read_text(encoding="utf-8").strip()
        if cached and _bus_reachable(gdbus_path, cached):
            return cached

    daemon = find_dbus_daemon()
    if not daemon:
        raise BusError(
            "dbus-daemon not found. Install it (MSYS2: 'pacman -S mingw-w64-x86_64-dbus') "
            "or set INKSCAPE_MCP_DBUS_DAEMON to its path."
        )

    addr_out = STATE_DIR / "dbus_daemon.addr"
    if addr_out.exists():
        addr_out.unlink()

    # dbus-daemon prints the address to stdout once, then keeps serving. Redirect to a
    # file and start detached so it outlives this process.
    with addr_out.open("w", encoding="utf-8") as fh:
        subprocess.Popen(  # noqa: S603 — fixed daemon path
            [daemon, "--session", "--print-address", "--nofork"],
            stdout=fh,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_DETACHED,
            close_fds=True,
        )

    deadline = time.monotonic() + _BUS_PRINT_TIMEOUT_S
    address = ""
    while time.monotonic() < deadline:
        if addr_out.exists():
            text = addr_out.read_text(encoding="utf-8").strip()
            line = text.splitlines()[0].strip() if text else ""
            if line and "guid=" in line:
                address = line
                break
        time.sleep(_POLL_INTERVAL_S)
    if not address:
        raise BusError("dbus-daemon did not print a bus address in time")

    ADDRESS_FILE.write_text(address, encoding="utf-8")
    log.info("Started dbus-daemon session bus at %s", address)
    return address


# ---- inkscape lifecycle ------------------------------------------------------------


def _inkscape_registered(gdbus_path: str, address: str) -> bool:
    """True once Inkscape has a live document window on the bus.

    The app name registers a beat before the document object
    (``/org/inkscape/Inkscape/document/N``); window-scope ops need the document, so
    "ready" means a numeric document child exists — not merely that the app pings.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — fixed gdbus path
            [
                gdbus_path,
                "introspect",
                "--address",
                address,
                "--dest",
                "org.inkscape.Inkscape",
                "--object-path",
                "/org/inkscape/Inkscape/document",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    import re

    return re.search(r"node\s+\d+\s*\{", proc.stdout) is not None


_BLANK_CANVAS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'width="210mm" height="297mm" viewBox="0 0 210 297" version="1.1">\n'
    '  <sodipodi:namedview inkscape:document-units="mm"/>\n'
    "</svg>\n"
)


def default_canvas() -> str:
    """Path to a persistent blank canvas, created on first use.

    Inkscape launched with NO file shows the welcome screen and exports no document
    object over D-Bus, so window-scope ops have nothing to target. Opening a concrete
    file skips the welcome screen and guarantees a ``/document/N`` node. This file is the
    default shared canvas when the caller doesn't specify one.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / "canvas.svg"
    if not path.exists():
        path.write_text(_BLANK_CANVAS, encoding="utf-8")
    return str(path)


def ensure_inkscape(gdbus_path: str, address: str, inkscape_executable: str, open_path: str | None = None) -> bool:
    """Ensure Inkscape is running on ``address``; launch it under the bus if not.

    Returns True if Inkscape is registered (already-running or freshly launched and
    registered within the timeout). Launch is detached so closing the MCP server does
    not kill the user's editor. When ``open_path`` is omitted, a default blank canvas is
    opened so a live document window exists.
    """
    if _inkscape_registered(gdbus_path, address):
        return True

    if not inkscape_executable or not Path(inkscape_executable).exists():
        raise BusError(f"Inkscape executable not found: {inkscape_executable!r}")

    env = dict(os.environ)
    env["DBUS_SESSION_BUS_ADDRESS"] = address
    argv = [inkscape_executable, open_path or default_canvas()]

    log.info("Launching Inkscape under MCP session bus: %s", argv)
    subprocess.Popen(  # noqa: S603 — inkscape path validated above
        argv,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_DETACHED,
        close_fds=True,
    )

    deadline = time.monotonic() + _INKSCAPE_REGISTER_TIMEOUT_S
    while time.monotonic() < deadline:
        if _inkscape_registered(gdbus_path, address):
            return True
        time.sleep(_POLL_INTERVAL_S)
    return False


def is_windows() -> bool:
    return sys.platform == "win32"
