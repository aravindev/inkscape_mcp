"""Windows D-Bus client for the running Inkscape GUI, via the bundled ``gdbus.exe``.

This class is a drop-in for ``InkscapeDBus`` — identical method surface
(``is_available``/``list_actions``/``describe``/``activate``/``open_file``/
``list_windows``) — selected by ``tools.live._get_bus()`` on Windows.

Object-path note (Inkscape 1.4.x): app actions live at ``/org/inkscape/Inkscape`` and
window/document-scope actions at ``/org/inkscape/Inkscape/document/N`` — NOT
``/org/inkscape/Inkscape/window/N`` (which older Inkscape used and the jeepney client
still hardcodes).
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

BUS_NAME = "org.inkscape.Inkscape"
APP_PATH = "/org/inkscape/Inkscape"
DOCUMENT_PATH_PREFIX = "/org/inkscape/Inkscape/document"

# gdbus call timeout (seconds). Actions are local IPC; generous for export-do etc.
_CALL_TIMEOUT_S = 30.0

# Single-quoted token extractor for List output: (['a', 'b.c', ...],)
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
# Describe output: ((true, signature 's', [<'null'>]),)  /  ((false, signature '', @av []),)
_DESCRIBE = re.compile(r"\((true|false),\s*signature\s*'([^']*)'")


class GDBusError(RuntimeError):
    """A gdbus invocation returned a D-Bus error or non-zero exit."""


class WinInkscapeDBus:
    """gdbus.exe-backed bridge to a running Inkscape GUI on a Windows TCP session bus."""

    def __init__(self, gdbus_path: str, bus_address: str) -> None:
        self._gdbus = gdbus_path
        self._address = bus_address

    # ---- low-level gdbus invocation -------------------------------------------------

    def _run(self, args: list[str]) -> str:
        """Run ``gdbus <args>`` and return stdout. Raise GDBusError on failure."""
        cmd = [self._gdbus, *args]
        try:
            proc = subprocess.run(  # noqa: S603 — cmd[0] is a fixed gdbus path; args are built here
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_CALL_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GDBusError(f"gdbus timed out after {_CALL_TIMEOUT_S}s: {args}") from exc
        if proc.returncode != 0:
            raise GDBusError((proc.stderr or proc.stdout or "gdbus failed").strip())
        return proc.stdout

    def _call(self, object_path: str, method: str, *method_args: str) -> str:
        return self._run(
            [
                "call",
                "--address",
                self._address,
                "--dest",
                BUS_NAME,
                "--object-path",
                object_path,
                "--method",
                method,
                *method_args,
            ]
        )

    def _introspect(self, object_path: str) -> str:
        return self._run(["introspect", "--address", self._address, "--dest", BUS_NAME, "--object-path", object_path])

    # ---- scope helpers --------------------------------------------------------------

    def _scope_path(self, scope: str, window_id: int) -> str:
        if scope == "app":
            return APP_PATH
        if scope == "window":
            return f"{DOCUMENT_PATH_PREFIX}/{window_id}"
        raise ValueError(f"scope must be 'app' or 'window', got {scope!r}")

    # ---- public surface (mirrors InkscapeDBus) --------------------------------------

    def is_available(self) -> bool:
        """True if the bus is reachable AND Inkscape has registered on it.

        Peer.Ping is addressed to the Inkscape name itself, so it only succeeds when
        Inkscape is actually registered (the bus daemon does not own that name).
        """
        try:
            self._call(APP_PATH, "org.freedesktop.DBus.Peer.Ping")
        except (GDBusError, OSError):
            return False
        return True

    def list_actions(self, scope: str = "app", window_id: int = 1) -> list[str]:
        out = self._call(self._scope_path(scope, window_id), "org.gtk.Actions.List")
        return _QUOTED.findall(out)

    def describe(self, action: str, scope: str = "app", window_id: int = 1) -> tuple[bool, str, list]:
        """Return (enabled, param_signature, defaults). Defaults are not parsed (unused)."""
        out = self._call(self._scope_path(scope, window_id), "org.gtk.Actions.Describe", action)
        m = _DESCRIBE.search(out)
        if not m:
            raise GDBusError(f"could not parse Describe output for {action!r}: {out!r}")
        enabled = m.group(1) == "true"
        signature = m.group(2)
        return enabled, signature, []

    def _format_param(self, signature: str, value: Any) -> str:
        """Format a single GVariant value for the gtk action's parameter signature."""
        if signature == "s":
            escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
            return f"<'{escaped}'>"
        if signature == "b":
            return f"<{'true' if value else 'false'}>"
        if signature in ("i", "u", "x", "t"):
            type_word = {"i": "int32", "u": "uint32", "x": "int64", "t": "uint64"}[signature]
            return f"<{type_word} {int(value)}>"
        if signature == "d":
            return f"<{float(value)}>"
        # Unknown/complex signature: pass through best-effort as a string variant.
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"<'{escaped}'>"

    def activate(
        self,
        action: str,
        args: list[Any] | None = None,
        scope: str = "app",
        window_id: int = 1,
    ) -> None:
        """Activate ``action`` with optional single parameter, mirroring InkscapeDBus."""
        _, signature, _ = self.describe(action, scope=scope, window_id=window_id)
        if signature:
            if not args:
                raise ValueError(f"action {action!r} requires a parameter of signature {signature!r}")
            params_av = f"[{self._format_param(signature, args[0])}]"
        else:
            params_av = "[]"
        # org.gtk.Actions.Activate signature is (sava{sv}): name, params, platform-data.
        self._call(self._scope_path(scope, window_id), "org.gtk.Actions.Activate", action, params_av, "{}")

    def open_file(self, path: str) -> None:
        import os

        abs_path = os.path.abspath(path).replace("\\", "/")
        uri = f"file:///{abs_path.lstrip('/')}"
        self._call(APP_PATH, "org.freedesktop.Application.Open", f"['{uri}']", "{}")

    def list_windows(self) -> list[int]:
        """Numeric child nodes under .../document — the live document/window ids."""
        out = self._introspect(DOCUMENT_PATH_PREFIX)
        ids: list[int] = []
        for m in re.finditer(r"node\s+(\d+)\s*\{", out):
            ids.append(int(m.group(1)))
        return sorted(set(ids))
