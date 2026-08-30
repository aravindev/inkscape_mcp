"""Bridge for invoking custom inkex extensions from the MCP.

The MCP writes a JSON spec into a shared exchange directory, fires the
extension via D-Bus, and reads a JSON result the extension writes back.
Two architectural wins over the file-edit + document-revert dance:

  1. Inkscape records each extension invocation as a single undoable command,
     so MCP-driven edits stay in the user's undo history.
  2. Provides a return channel for inspection ops — D-Bus actions have no
     way to return data, but a JSON result file does.

Layout:
  ~/.cache/inkscape_mcp/exchange/
    input.json   (MCP -> extension)
    result.json  (extension -> MCP)
    stderr.txt   (extension stderr capture, if any)

Concurrency: the filenames above are fixed, so two overlapping invocations would
trample each other — B's spec would overwrite A's input.json, and B's unlink would
delete the result A is waiting for. Per-call unique names aren't an option: the
`.noprefs` D-Bus action carries no arguments, so the plugin has no way to be told
which file to read. Instead every invocation is serialised through `BRIDGE_LOCK`,
which also guards the shared (non-thread-safe) jeepney connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .dbus_client import InkscapeDBus

log = logging.getLogger(__name__)

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

# Serialises every use of the exchange directory AND of the live D-Bus connection.
# Live edits are inherently serial against a single GUI, so this costs nothing in
# practice and removes a whole class of cross-talk between concurrent tool calls.
BRIDGE_LOCK = asyncio.Lock()


def _user_extensions_dir() -> Path:
    """Inkscape's per-user extensions dir, platform-aware.

    Windows keeps preferences/extensions under ``%APPDATA%\\inkscape``; Linux/macOS use
    the XDG ``~/.config/inkscape`` location.
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return Path(appdata) / "inkscape" / "extensions" / "inkscape_mcp"
    return Path(os.path.expanduser("~/.config/inkscape/extensions/inkscape_mcp"))


INSTALL_DIR = _user_extensions_dir()
VERSION_FILE = INSTALL_DIR / "VERSION"

# Bump when the bundled plugins change — triggers reinstall on next MCP startup.
# 10: mcp_edit_xml rejects non-element XPath results instead of dying on AttributeError
#     (which left result.json unwritten and hung the caller until its timeout).
PLUGINS_VERSION = "10"

# Used to detect whether a fresh install has been picked up by a running Inkscape.
ECHO_ACTION = "org.inkscape.mcp.echo.noprefs"


@dataclass
class ExchangeResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    stderr: str = ""
    error: str = ""


async def invoke_extension(
    bus: InkscapeDBus,
    action: str,
    spec: dict[str, Any],
    *,
    scope: str = "app",
    window_id: int = 1,
    timeout_s: float = 30.0,
) -> ExchangeResult:
    """Drop a spec to the exchange dir, fire the extension, wait for result.json.

    `action` is the full D-Bus action name (e.g. 'org.inkscape.mcp.echo.noprefs').
    `spec` is JSON-serialised into input.json before invocation. Returns the
    parsed result, or an ExchangeResult with success=False on any failure
    (timeout, malformed result, bus error).

    Held under `BRIDGE_LOCK` for its whole duration — the exchange filenames are fixed,
    so a concurrent call would clobber this one's input and result.
    """
    async with BRIDGE_LOCK:
        return await _invoke_extension_locked(bus, action, spec, scope=scope, window_id=window_id, timeout_s=timeout_s)


async def _invoke_extension_locked(
    bus: InkscapeDBus,
    action: str,
    spec: dict[str, Any],
    *,
    scope: str,
    window_id: int,
    timeout_s: float,
) -> ExchangeResult:
    """Body of `invoke_extension`. Caller must already hold `BRIDGE_LOCK`."""
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    input_path = EXCHANGE_DIR / "input.json"
    result_path = EXCHANGE_DIR / "result.json"
    stderr_path = EXCHANGE_DIR / "stderr.txt"

    for p in (result_path, stderr_path):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    input_path.write_text(json.dumps(spec))

    # Deliberately NOT run via asyncio.to_thread: InkscapeDBus keeps one shared jeepney
    # connection, and handing it to a worker thread while another coroutine uses it from
    # the event loop corrupts the reply stream. Activate is a sub-millisecond local IPC
    # round-trip anyway; the part that actually takes time is the poll below, which does
    # yield.
    try:
        bus.activate(action, scope=scope, window_id=window_id)
    except Exception as exc:
        return ExchangeResult(success=False, error=f"D-Bus activate failed: {exc}")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            break
        await asyncio.sleep(0.05)
    else:
        stderr = _read_text_safe(stderr_path)
        return ExchangeResult(
            success=False,
            error=f"extension did not produce result within {timeout_s}s",
            stderr=stderr,
        )

    try:
        data = json.loads(result_path.read_text())
    except json.JSONDecodeError as exc:
        return ExchangeResult(success=False, error=f"result not valid JSON: {exc}")

    if not isinstance(data, dict):
        return ExchangeResult(success=False, error="result must decode to a JSON object")

    return ExchangeResult(success=True, data=data)


def is_installed() -> bool:
    """True if our plugins are installed at the current version."""
    if not VERSION_FILE.exists():
        return False
    try:
        return VERSION_FILE.read_text().strip() == PLUGINS_VERSION
    except OSError:
        return False


def install_plugins() -> dict[str, Any]:
    """Copy bundled mcp_* plugins into Inkscape's user extensions dir.

    Idempotent — only copies on version mismatch. Inkscape must be restarted
    for newly-installed extensions to register as D-Bus actions.
    """
    if is_installed():
        return {"installed": True, "action": "no-op", "version": PLUGINS_VERSION}

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    plugin_root = resources.files("inkscape_mcp.plugins")
    copied: list[str] = []
    for entry in plugin_root.iterdir():
        name = entry.name
        if not name.startswith("mcp_"):
            continue
        if not (name.endswith(".inx") or name.endswith(".py")):
            continue
        dest = INSTALL_DIR / name
        with entry.open("rb") as src, dest.open("wb") as dst:
            dst.write(src.read())
        if name.endswith(".py"):
            dest.chmod(0o755)
        copied.append(name)

    VERSION_FILE.write_text(PLUGINS_VERSION)
    return {
        "installed": True,
        "action": "copied",
        "version": PLUGINS_VERSION,
        "files": copied,
        "needs_restart": True,
    }


def needs_inkscape_restart(bus: InkscapeDBus) -> bool:
    """True if our plugins are installed on disk but the live Inkscape hasn't picked them up.

    Inkscape scans extensions only at startup, so first-time install requires
    a restart before the new action surface appears.
    """
    if not is_installed():
        return False
    try:
        actions = set(bus.list_actions("app"))
    except Exception:
        return False
    return ECHO_ACTION not in actions


def bridge_status() -> dict[str, Any]:
    """Snapshot of the extension bridge state, for diagnostics."""
    return {
        "installed": is_installed(),
        "version": PLUGINS_VERSION,
        "install_dir": str(INSTALL_DIR),
        "exchange_dir": str(EXCHANGE_DIR),
    }


def _read_text_safe(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""
