"""Pick a D-Bus session for the live bridge, and start Inkscape on it when we own the bus.

Three situations, one rule:

* A real session bus is reachable (normal Linux desktop, or ``DBUS_SESSION_BUS_ADDRESS`` set
  by the user): use it and leave the user's Inkscape alone.
* No session bus (macOS, most Windows setups): run the pure-Python :mod:`embedded_bus`
  inside this process and launch Inkscape *under* it. An Inkscape the user started by hand
  is not on our bus and cannot be reached; that is a limit of D-Bus, not of this server.
* ``INKSCAPE_MCP_BUS=embedded|system`` forces either behaviour.

Existing Windows setups that already have MSYS2 ``dbus-daemon`` keep using it (that path is
exercised upstream); everything else gets the embedded bus.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .bus_connect import open_bus_connection
from .embedded_bus import EmbeddedBus
from .proc_utils import add_bundled_tools_to_path, child_kwargs, terminate_popen_tree

log = logging.getLogger(__name__)

BUS_ENV = "INKSCAPE_MCP_BUS"  # "embedded" | "system"
_INKSCAPE_NAME = "org.inkscape.Inkscape"
_REGISTER_TIMEOUT_S = 30.0

_lock = threading.Lock()
_embedded: EmbeddedBus | None = None
_inkscape_proc: subprocess.Popen[bytes] | None = None
_active_path: str | None = None  # last document we opened; used for the save fallback

_BLANK_CANVAS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'width="800" height="600" viewBox="0 0 800 600"><g inkscape:groupmode="layer" id="layer1" '
    'inkscape:label="Layer 1"/></svg>\n'
)


def system_bus_address() -> str | None:
    """Address of a real session bus, if there is one."""
    env = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if env:
        return env
    if sys.platform.startswith("linux"):
        sock = Path(f"/run/user/{os.getuid()}/bus")
        if sock.exists():
            return f"unix:path={sock}"
    return None


def use_embedded() -> bool:
    """Should this process own the bus?"""
    forced = os.environ.get(BUS_ENV, "").lower()
    if forced == "embedded":
        return True
    if forced == "system":
        return False
    return system_bus_address() is None


def active_address() -> str | None:
    """The embedded bus address if we started one (what ``InkscapeDBus()`` should use)."""
    return _embedded.address if _embedded else None


def resolve_address() -> str:
    """Address a client should connect to right now."""
    addr = active_address() or system_bus_address()
    if addr is None:
        raise ConnectionError("no D-Bus session bus available (the embedded bus has not been started)")
    return addr


def ensure_embedded_bus() -> str:
    global _embedded
    with _lock:
        if _embedded is None:
            bus = EmbeddedBus(tcp=sys.platform == "win32")
            bus.start()
            _embedded = bus
        return _embedded.address


def stop_embedded_bus() -> None:
    global _embedded, _inkscape_proc
    with _lock:
        if _inkscape_proc is not None:
            terminate_popen_tree(_inkscape_proc)
        _inkscape_proc = None
        if _embedded is not None:
            _embedded.stop()
            _embedded = None


def default_canvas() -> str:
    """A persistent blank canvas. Opening a concrete file skips Inkscape's welcome screen,
    which exports no document object and so leaves nothing to target."""
    d = Path(tempfile.gettempdir()) / "inkscape_mcp"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "canvas.svg"
    if not path.exists():
        path.write_text(_BLANK_CANVAS, encoding="utf-8")
    return str(path)


def active_document() -> str | None:
    return _active_path


def set_active_document(path: str) -> None:
    global _active_path
    _active_path = path


def _registered(address: str) -> bool:
    from jeepney.bus_messages import DBus

    try:
        conn = open_bus_connection(address, timeout=2.0)
    except (OSError, TimeoutError, ConnectionError):
        return False
    try:
        reply = conn.send_and_get_reply(DBus().NameHasOwner(_INKSCAPE_NAME), timeout=3)
        return bool(reply.body[0])
    except Exception:
        return False
    finally:
        conn.close()


def _document_exported(address: str) -> bool:
    """True once Inkscape has published at least one ``/document/N`` object."""
    import xml.etree.ElementTree as ET

    from jeepney import DBusAddress, new_method_call

    try:
        conn = open_bus_connection(address, timeout=2.0)
    except (OSError, TimeoutError, ConnectionError):
        return False
    try:
        where = DBusAddress(
            "/org/inkscape/Inkscape/document",
            bus_name=_INKSCAPE_NAME,
            interface="org.freedesktop.DBus.Introspectable",
        )
        reply = conn.send_and_get_reply(new_method_call(where, "Introspect"), timeout=3)
        root = ET.fromstring(reply.body[0])  # noqa: S314 - introspection XML from our own local bus
        return any(n.get("name", "").isdigit() for n in root.findall("node"))
    except Exception:
        return False
    finally:
        conn.close()


def ensure_inkscape(inkscape_exe: str, open_path: str | None = None) -> bool:
    """Make sure an Inkscape GUI is registered on the embedded bus. True when it is."""
    global _inkscape_proc, _active_path
    address = ensure_embedded_bus()
    if _registered(address) and _document_exported(address):
        return True
    if not inkscape_exe or not Path(inkscape_exe).exists():
        raise FileNotFoundError(f"Inkscape executable not found: {inkscape_exe!r}")

    target = open_path or default_canvas()
    env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address)
    add_bundled_tools_to_path(env, inkscape_exe)
    kwargs = child_kwargs(detached=True)
    log.info("launching Inkscape under embedded bus: %s", target)
    _inkscape_proc = subprocess.Popen(  # noqa: S603 - path validated above
        [inkscape_exe, target],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **kwargs,
    )
    _active_path = target

    deadline = time.monotonic() + _REGISTER_TIMEOUT_S
    while time.monotonic() < deadline:
        if _inkscape_proc.poll() is not None:
            return False
        # Registered is not ready: the document object appears a moment later, and callers
        # that act on "the active document" would otherwise race it.
        if _registered(address) and _document_exported(address):
            return True
        time.sleep(0.3)
    return False
