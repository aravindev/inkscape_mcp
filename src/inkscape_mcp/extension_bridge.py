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
which file to read. Three layers keep invocations apart:

  * `BRIDGE_LOCK` serialises calls inside one server process (and guards the shared,
    non-thread-safe jeepney connection).
  * `exchange/.lock` (an `flock`) serialises calls ACROSS server processes. Every
    MCP client session spawns its own server, all driving the same Inkscape through
    the same exchange directory; without this, one session read another's result.
  * Every spec carries `_request_id` and `_plugin`. A plugin ignores a spec addressed
    to another plugin, claims the spec by renaming input.json (so a late, queued
    duplicate finds nothing to run), and echoes `_request_id` in its result; the
    bridge rejects any result whose id is not its own. On timeout the bridge withdraws
    input.json so an invocation Inkscape runs later cannot execute a stale spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .dbus_client import InkscapeDBus

try:  # POSIX only; Windows falls back to the in-process lock alone.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

# Serialises every use of the exchange directory AND of the live D-Bus connection.
# Live edits are inherently serial against a single GUI, so this costs nothing in
# practice and removes a whole class of cross-talk between concurrent tool calls.
BRIDGE_LOCK = asyncio.Lock()


def _user_extensions_dir() -> Path:
    """Install into the live profile, isolated from normal Inkscape on macOS."""
    from . import platform_support

    return platform_support.live_profile_dir() / "extensions" / "inkscape_mcp"


INSTALL_DIR = _user_extensions_dir()
VERSION_FILE = INSTALL_DIR / "VERSION"

# Bump when the bundled plugins change — triggers reinstall on next MCP startup.
# 10: mcp_edit_xml rejects non-element XPath results instead of dying on AttributeError
#     (which left result.json unwritten and hung the caller until its timeout).
# 11: computed_style resolves the CSS cascade in the right order (inline style="" beats
#     the presentation attribute — it used to report the losing declaration), and every
#     plugin result now names the document it ran against via `active_document`.
# 12: cross-process isolation — plugins honour `_plugin`, claim input.json, echo
#     `_request_id`, and write result.json atomically.
PLUGINS_VERSION = "12"

# Used to detect whether a fresh install has been picked up by a running Inkscape.
ECHO_ACTION = "org.inkscape.mcp.echo.noprefs"


@dataclass
class ExchangeResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    stderr: str = ""
    error: str = ""


# Lower bound for every extension timeout, in seconds. Heavy documents (many pages,
# filters, clones) routinely take longer than the 10-15 s some call sites ask for.
# Override with INKSCAPE_MCP_EXTENSION_TIMEOUT.
_DEFAULT_MIN_TIMEOUT_S = 30.0
# How long a result.json may stay unparseable before it counts as malformed.
_MALFORMED_GRACE_S = 0.5
# How long to wait for another server process to release the exchange directory.
_CROSS_PROCESS_LOCK_WAIT_S = 120.0


def _min_timeout_s() -> float:
    raw = os.environ.get("INKSCAPE_MCP_EXTENSION_TIMEOUT", "")
    try:
        value = float(raw) if raw else _DEFAULT_MIN_TIMEOUT_S
    except ValueError:
        log.warning("ignoring non-numeric INKSCAPE_MCP_EXTENSION_TIMEOUT=%r", raw)
        value = _DEFAULT_MIN_TIMEOUT_S
    return max(value, 0.0)


def effective_timeout(timeout_s: float) -> float:
    """The timeout actually applied: the caller's value, floored by the configured minimum."""
    return max(timeout_s, _min_timeout_s())


def plugin_name_for(action: str) -> str:
    """'org.inkscape.mcp.edit-xml.noprefs' -> 'edit_xml' (the name plugins match against)."""
    name = action.removeprefix("org.inkscape.mcp.").removesuffix(".noprefs")
    return name.replace("-", "_")


@asynccontextmanager
async def _cross_process_lock(wait_s: float = _CROSS_PROCESS_LOCK_WAIT_S):
    """Hold `exchange/.lock` so no other MCP server process uses the exchange meanwhile.

    Polls a non-blocking flock rather than blocking, so the event loop stays responsive.
    """
    if fcntl is None:
        yield
        return
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(EXCHANGE_DIR / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"another inkscape_mcp process held the exchange lock for over {wait_s:.0f}s"
                    ) from None
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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

    Held under `BRIDGE_LOCK` (in-process) and `exchange/.lock` (cross-process) for its
    whole duration — the exchange filenames are fixed, so a concurrent call would
    clobber this one's input and result.
    """
    async with BRIDGE_LOCK:
        try:
            async with _cross_process_lock():
                return await _invoke_extension_locked(
                    bus, action, spec, scope=scope, window_id=window_id, timeout_s=timeout_s
                )
        except TimeoutError as exc:
            return ExchangeResult(success=False, error=str(exc))


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("could not remove %s", path, exc_info=True)


async def _invoke_extension_locked(
    bus: InkscapeDBus,
    action: str,
    spec: dict[str, Any],
    *,
    scope: str,
    window_id: int,
    timeout_s: float,
) -> ExchangeResult:
    """Body of `invoke_extension`. Caller must already hold both locks."""
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    input_path = EXCHANGE_DIR / "input.json"
    result_path = EXCHANGE_DIR / "result.json"
    stderr_path = EXCHANGE_DIR / "stderr.txt"

    for p in (result_path, stderr_path):
        _unlink_quietly(p)

    request_id = uuid.uuid4().hex
    envelope = {**spec, "_request_id": request_id, "_plugin": plugin_name_for(action)}
    tmp_input = EXCHANGE_DIR / f".input-{request_id}.tmp"
    tmp_input.write_text(json.dumps(envelope))
    os.replace(tmp_input, input_path)

    # Deliberately NOT run via asyncio.to_thread: InkscapeDBus keeps one shared jeepney
    # connection, and handing it to a worker thread while another coroutine uses it from
    # the event loop corrupts the reply stream. Activate is a sub-millisecond local IPC
    # round-trip anyway; the part that actually takes time is the poll below, which does
    # yield.
    try:
        bus.activate(action, scope=scope, window_id=window_id)
    except Exception as exc:
        _unlink_quietly(input_path)
        return ExchangeResult(success=False, error=f"D-Bus activate failed: {exc}")

    timeout_s = effective_timeout(timeout_s)
    deadline = time.monotonic() + timeout_s
    data: Any = None
    malformed_since: float | None = None
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                data = json.loads(result_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                # Legacy plugins write non-atomically, so a parse failure may just be a
                # half-written file. Allow a short grace period before calling it bad.
                now = time.monotonic()
                malformed_since = malformed_since or now
                if now - malformed_since > _MALFORMED_GRACE_S:
                    _unlink_quietly(input_path)
                    return ExchangeResult(success=False, error=f"result not valid JSON: {exc}")
                await asyncio.sleep(0.05)
                continue
            malformed_since = None
            if not isinstance(data, dict):
                _unlink_quietly(input_path)
                return ExchangeResult(success=False, error="result must decode to a JSON object")
            echoed = data.pop("_request_id", None)
            if echoed is None or echoed == request_id:
                break
            # A result for some other request (a late invocation of an earlier,
            # timed-out call). Discard it and keep waiting for ours.
            log.warning("discarding foreign extension result (request %s)", echoed)
            _unlink_quietly(result_path)
            data = None
        await asyncio.sleep(0.05)
    else:
        # Withdraw the spec so a queued invocation that runs later finds nothing to do
        # instead of executing a stale request against the document.
        _unlink_quietly(input_path)
        stderr = _read_text_safe(stderr_path)
        return ExchangeResult(
            success=False,
            error=f"extension did not produce result within {timeout_s}s",
            stderr=stderr,
        )

    _unlink_quietly(input_path)
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


def needs_inkscape_restart(bus: Any) -> bool:
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
