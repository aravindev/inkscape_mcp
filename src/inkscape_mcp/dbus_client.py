"""D-Bus client for talking to a running Inkscape GUI instance."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import DBusErrorResponse

# Bus name and root object path are fixed by Inkscape's GApplication setup.
BUS_NAME = "org.inkscape.Inkscape"
APP_PATH = "/org/inkscape/Inkscape"
WINDOW_PATH_PREFIX = "/org/inkscape/Inkscape/window"


class InkscapeDBus:
    """Blocking jeepney bridge to a running Inkscape 1.4.x GUI on the session bus."""

    def __init__(self) -> None:
        self._conn: DBusConnection | None = None

    def _connect(self) -> DBusConnection:
        if self._conn is None:
            self._conn = open_dbus_connection(bus="SESSION")
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: S110 — best-effort cleanup; failure here cannot be acted on
                pass
            self._conn = None

    def _send(self, msg):
        # Reconnect once on a broken pipe; otherwise propagate. Raise on D-Bus errors.
        try:
            conn = self._connect()
            reply = conn.send_and_get_reply(msg)
        except (BrokenPipeError, ConnectionError, OSError):
            self._close()
            conn = self._connect()
            reply = conn.send_and_get_reply(msg)
        if reply.header.message_type == MessageType.error:
            raise DBusErrorResponse(reply)
        return reply

    def _scope_path(self, scope: str, window_id: int) -> str:
        if scope == "app":
            return APP_PATH
        if scope == "window":
            return f"{WINDOW_PATH_PREFIX}/{window_id}"
        raise ValueError(f"scope must be 'app' or 'window', got {scope!r}")

    def is_available(self) -> bool:
        addr = DBusAddress(
            object_path=APP_PATH,
            bus_name=BUS_NAME,
            interface="org.freedesktop.DBus.Peer",
        )
        msg = new_method_call(addr, "Ping", "", ())
        try:
            self._send(msg)
            return True
        except (DBusErrorResponse, OSError, ConnectionError):
            return False

    def list_actions(self, scope: str = "app", window_id: int = 1) -> list[str]:
        addr = DBusAddress(
            object_path=self._scope_path(scope, window_id),
            bus_name=BUS_NAME,
            interface="org.gtk.Actions",
        )
        msg = new_method_call(addr, "List", "", ())
        reply = self._send(msg)
        return list(reply.body[0])

    def describe(self, action: str, scope: str = "app", window_id: int = 1) -> tuple[bool, str, list]:
        """Return (enabled, param_signature, defaults)."""
        addr = DBusAddress(
            object_path=self._scope_path(scope, window_id),
            bus_name=BUS_NAME,
            interface="org.gtk.Actions",
        )
        msg = new_method_call(addr, "Describe", "s", (action,))
        reply = self._send(msg)
        enabled, signature, defaults = reply.body[0]
        return bool(enabled), str(signature), list(defaults)

    def _wrap_variant(self, signature: str, value: Any) -> tuple[str, Any]:
        # gtk action params are nearly always one of these scalar types.
        if signature == "s":
            return ("s", str(value))
        if signature == "i":
            return ("i", int(value))
        if signature == "u":
            return ("u", int(value))
        if signature == "x":
            return ("x", int(value))
        if signature == "t":
            return ("t", int(value))
        if signature == "d":
            return ("d", float(value))
        if signature == "b":
            return ("b", bool(value))
        # Fall back to passing the value through with the declared signature.
        return (signature, value)

    def activate(
        self,
        action: str,
        args: list[Any] | None = None,
        scope: str = "app",
        window_id: int = 1,
    ) -> None:
        _, signature, _ = self.describe(action, scope=scope, window_id=window_id)
        variants: list[tuple[str, Any]] = []
        if signature:
            if not args:
                raise ValueError(f"action {action!r} requires a parameter of signature {signature!r}")
            variants.append(self._wrap_variant(signature, args[0]))

        addr = DBusAddress(
            object_path=self._scope_path(scope, window_id),
            bus_name=BUS_NAME,
            interface="org.gtk.Actions",
        )
        msg = new_method_call(addr, "Activate", "sava{sv}", (action, variants, {}))
        self._send(msg)

    def open_file(self, path: str) -> None:
        abs_path = os.path.abspath(path)
        addr = DBusAddress(
            object_path=APP_PATH,
            bus_name=BUS_NAME,
            interface="org.freedesktop.Application",
        )
        msg = new_method_call(addr, "Open", "asa{sv}", ([f"file://{abs_path}"], {}))
        self._send(msg)

    def list_windows(self) -> list[int]:
        addr = DBusAddress(
            object_path=WINDOW_PATH_PREFIX,
            bus_name=BUS_NAME,
            interface="org.freedesktop.DBus.Introspectable",
        )
        msg = new_method_call(addr, "Introspect", "", ())
        reply = self._send(msg)
        xml = reply.body[0]
        root = ET.fromstring(xml)  # noqa: S314 — XML produced by trusted local D-Bus introspection (org.freedesktop.DBus.Introspectable)
        ids: list[int] = []
        for node in root.findall("node"):
            name = node.get("name")
            if name and name.isdigit():
                ids.append(int(name))
        return sorted(ids)
