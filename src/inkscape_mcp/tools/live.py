"""Live-Inkscape bridge: drive the running GUI via D-Bus + clipboard."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .. import bus_manager
from ..clipboard import stage_svg_fragment
from ..dbus_client import InkscapeDBus
from ..extension_bridge import invoke_extension
from ..win_dbus_client import WinInkscapeDBus


class LiveResult(BaseModel):
    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


_BUS: InkscapeDBus | None = None

_SCRATCH_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp"))
# How long we wait for the exported file to appear after triggering export-do.
_EXPORT_POLL_TIMEOUT_S = 5.0
_EXPORT_POLL_INTERVAL_S = 0.05

_AUTO_SAVE_ENV = "INKSCAPE_MCP_AUTO_SAVE"

# Actions that don't modify the document. After firing these we skip the implicit
# document-save. Curated; conservative — when in doubt, treat as mutating.
_READ_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        # Selection changes (select-*, not selection-* which mutates)
        "select-all",
        "select-clear",
        "select-none",
        "select-invert",
        "select-by-id",
        "select-by-selector",
        "select-by-element",
        "select-by-class",
        "select-list",
        "select-original",
        "select-same-fill",
        "select-same-stroke",
        # Clipboard read
        "copy",
        # Document lifecycle — saving these would recurse or is irrelevant
        "document-save",
        "document-save-as",
        "document-save-copy",
        "document-revert",
        "document-new",
        "document-close",
    }
)

_READ_ONLY_PREFIXES: tuple[str, ...] = (
    "zoom-",
    "view-",
    "canvas-",
    "window-",
    "focus-",
    "export-",
    "list-",
    "query-",
    "help-",
    "about-",
    "dialog-",
)


def _action_mutates_document(action: str) -> bool:
    """True if firing `action` should be followed by document-save."""
    if action in _READ_ONLY_ACTIONS:
        return False
    return not any(action.startswith(p) for p in _READ_ONLY_PREFIXES)


def _activate_with_optional_save(
    bus: InkscapeDBus,
    action: str,
    args: list[Any] | None = None,
    scope: str = "app",
    window_id: int = 1,
) -> bool:
    """Fire `action`, then fire document-save if `action` mutates the document.
    Returns True if save was fired. Save failure is swallowed — the primary edit
    succeeded, and a stale on-disk file shouldn't block the agent."""
    bus.activate(action, args, scope=scope, window_id=window_id)
    if os.environ.get(_AUTO_SAVE_ENV) == "0":
        return False
    if not _action_mutates_document(action):
        return False
    try:
        bus.activate("document-save", scope="window", window_id=window_id)
        return True
    except Exception:
        return False


def _resolve_window_id(bus: InkscapeDBus, requested: int) -> int:
    """Return `requested` if it's an open Inkscape window; otherwise fall back
    to the first available window. Lets callers pass the default
    ``window_id=1`` and still work after the user closes window 1 or opens
    new docs (window 2, 3, …).

    Raises ``RuntimeError`` if no windows are open at all — callers should
    have checked ``bus.is_available()`` first."""
    try:
        windows = bus.list_windows()
    except Exception:
        return requested  # Best-effort: fall through with what was asked.
    if not windows:
        raise RuntimeError("no Inkscape windows are open")
    if requested in windows:
        return requested
    return windows[0]


def _resolve_inkscape_exe(config: Any) -> str:
    exe = getattr(config, "inkscape_executable", None) if config is not None else None
    exe = exe or os.environ.get("INKS_INKSCAPE_BIN") or os.environ.get("INKSCAPE_BIN") or "inkscape"
    # Inkscape's detector may return inkscape.COM (console wrapper); the GUI binary
    # inkscape.exe sits beside it and launches without spawning a console window.
    if exe.lower().endswith("inkscape.com"):
        gui = Path(exe).with_name("inkscape.exe")
        if gui.exists():
            return str(gui)
    return exe


def _get_bus(config: Any = None) -> Any:
    """Return the platform-appropriate live bridge.

    Windows has no autostarted D-Bus session bus and jeepney can't speak the TCP bus, so
    we use a ``gdbus.exe``-backed client bound to a managed session bus (see
    ``bus_manager``). Linux/macOS keep the jeepney client. The Windows client is cheap to
    build and bound to a possibly-changing bus address, so it is not cached.
    """
    global _BUS
    if bus_manager.is_windows():
        inkscape_exe = _resolve_inkscape_exe(config)
        gdbus = bus_manager.find_gdbus(inkscape_exe)
        if not gdbus:
            raise RuntimeError("gdbus.exe not found (expected next to inkscape.exe or on PATH)")
        address = bus_manager.ensure_bus(gdbus)
        return WinInkscapeDBus(gdbus, address)
    if _BUS is None:
        _BUS = InkscapeDBus()
    return _BUS


def _auto_launch_inkscape(config: Any) -> bool:
    """Windows auto-manage: ensure a bus + a running Inkscape under it. Returns ready."""
    inkscape_exe = _resolve_inkscape_exe(config)
    gdbus = bus_manager.find_gdbus(inkscape_exe)
    if not gdbus:
        raise RuntimeError("gdbus.exe not found (expected next to inkscape.exe or on PATH)")
    address = bus_manager.ensure_bus(gdbus)
    return bus_manager.ensure_inkscape(gdbus, address, inkscape_exe)


def _result(
    operation: str,
    success: bool,
    message: str,
    data: dict[str, Any] | None = None,
    error: str = "",
    start: float | None = None,
) -> dict[str, Any]:
    elapsed = (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
    return LiveResult(
        success=success,
        operation=operation,
        message=message,
        data=data or {},
        execution_time_ms=elapsed,
        error=error,
    ).model_dump()


def _looks_like_selector(target: str) -> bool:
    # CSS-ish heuristic: '#', '.', '[', ' ', '>' etc.
    return any(ch in target for ch in "#.[ >:,*")


def _scratch_path() -> Path:
    _SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    return _SCRATCH_DIR / f"snap-{uuid.uuid4().hex}.svg"


def _export_document(bus: InkscapeDBus, scratch: Path) -> None:
    """Drive Inkscape's export-* actions to dump the current doc as plain-ish SVG."""
    if scratch.exists():
        scratch.unlink()
    bus.activate("export-filename", [str(scratch)], scope="app")
    bus.activate("export-type", ["svg"], scope="app")
    bus.activate("export-overwrite", [True], scope="app")
    bus.activate("export-do", scope="app")

    deadline = time.monotonic() + _EXPORT_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        if scratch.exists() and scratch.stat().st_size > 0:
            return
        time.sleep(_EXPORT_POLL_INTERVAL_S)
    raise TimeoutError(f"Inkscape did not produce {scratch} within {_EXPORT_POLL_TIMEOUT_S}s")


def _op_ping(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    if not bus.is_available():
        return _result(
            operation,
            False,
            "Inkscape D-Bus bridge not reachable (is the GUI running?)",
            data={"ok": False, "windows": [], "app_actions": 0, "window_actions": 0},
            start=start,
        )
    windows = bus.list_windows()
    app_actions = bus.list_actions("app")
    window_actions = bus.list_actions("window", windows[0]) if windows else []
    return _result(
        operation,
        True,
        f"Inkscape bridge live ({len(windows)} window(s))",
        data={
            "ok": True,
            "windows": windows,
            "app_actions": len(app_actions),
            "window_actions": len(window_actions),
        },
        start=start,
    )


def _op_get_document_xml(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    scratch = _scratch_path()
    _export_document(bus, scratch)
    xml = scratch.read_text(encoding="utf-8")
    return _result(
        operation,
        True,
        f"Exported document XML ({len(xml)} bytes)",
        data={"xml": xml, "path": str(scratch)},
        start=start,
    )


async def _op_get_selection(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    """Read the current selection via the mcp_inspect extension.

    Identical surface to ``inspect_selection``. Returns ``{count, ids, objects[],
    text}`` — no longer touches the system clipboard.
    """
    return await _do_inspect(bus, "selection", operation, start)


def _op_set_selection(bus: InkscapeDBus, operation: str, target: str, start: float) -> dict[str, Any]:
    if not target:
        return _result(
            operation,
            False,
            "target (id or selector) is required",
            error="missing target",
            start=start,
        )
    action = "select-by-selector" if _looks_like_selector(target) else "select-by-id"
    bus.activate(action, [target], scope="app")
    return _result(
        operation,
        True,
        f"activated {action!r} for {target!r}",
        data={"action": action, "target": target},
        start=start,
    )


def _op_insert_svg(
    bus: InkscapeDBus,
    operation: str,
    payload: str,
    window_id: int,
    start: float,
) -> dict[str, Any]:
    if not payload.strip():
        return _result(
            operation,
            False,
            "payload (SVG fragment) is required",
            error="empty payload",
            start=start,
        )
    stage_svg_fragment(payload)
    saved = _activate_with_optional_save(
        bus,
        "paste-in-place",
        scope="window",
        window_id=window_id,
    )
    return _result(
        operation,
        True,
        "staged SVG fragment and triggered paste-in-place",
        data={"window_id": window_id, "bytes": len(payload), "saved": saved},
        start=start,
    )


# Inkex code that reads the staged fragment and appends its child elements into the
# live document root. Used where Inkscape exposes no paste-in-place action (e.g. 1.4.x).
_INSERT_VIA_INKEX_CODE = (
    "import os as _os\n"
    "from lxml import etree as _ET\n"
    "_p = _os.path.expanduser('~/.cache/inkscape_mcp/exchange/insert_fragment.svg')\n"
    "_root = _ET.parse(_p).getroot()\n"
    "_added = 0\n"
    "for _c in list(_root):\n"
    "    svg.append(_c)\n"
    "    _added += 1\n"
    "result = {'added': _added}\n"
)


async def _op_insert_svg_via_inkex(
    bus: Any,
    operation: str,
    payload: str,
    start: float,
) -> dict[str, Any]:
    """Insert an SVG fragment by appending its children to the live document via inkex.

    Inkscape 1.4.x exposes no ``paste-in-place`` action over D-Bus, so the clipboard
    route is unavailable. We stage the fragment to the exchange dir and run the
    ``mcp_execute`` extension to splice its child elements into the document — one
    undoable ``MCP: Execute`` command, like every other bridge edit.
    """
    if not payload.strip():
        return _result(operation, False, "payload (SVG fragment) is required", error="empty payload", start=start)

    from ..extension_bridge import EXCHANGE_DIR

    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    (EXCHANGE_DIR / "insert_fragment.svg").write_text(payload, encoding="utf-8")

    result = await invoke_extension(bus, _EXECUTE_EXTENSION, {"python_code": _INSERT_VIA_INKEX_CODE}, timeout_s=30.0)
    if not result.success or result.data.get("ok") is False:
        message = result.error or result.data.get("error", "insert_svg failed")
        if result.stderr:
            message = f"{message}\nstderr:\n{result.stderr}"
        return _result(operation, False, message, data={"stderr": result.stderr}, error=result.error, start=start)

    added = (result.data.get("result") or {}).get("added", 0)
    return _result(
        operation,
        True,
        f"inserted {added} element(s) into the live document",
        data={"added": added, "bytes": len(payload)},
        start=start,
    )


def _op_delete_selected(bus: InkscapeDBus, operation: str, window_id: int, start: float) -> dict[str, Any]:
    # delete-selection is the explicit object-delete; `delete` is context-sensitive (text/nodes).
    # window_id must be threaded through: the follow-up document-save is window-scoped, so
    # defaulting it to 1 silently no-ops the save on any other window.
    saved = _activate_with_optional_save(bus, "delete-selection", scope="app", window_id=window_id)
    return _result(
        operation,
        True,
        "activated delete-selection",
        data={"action": "delete-selection", "window_id": window_id, "saved": saved},
        start=start,
    )


def _op_apply_action(
    bus: InkscapeDBus,
    operation: str,
    target: str,
    payload: str,
    window_id: int,
    start: float,
) -> dict[str, Any]:
    if not target:
        return _result(
            operation,
            False,
            "target (action name) is required",
            error="missing target",
            start=start,
        )
    app_actions = set(bus.list_actions("app"))
    window_actions = set(bus.list_actions("window", window_id))
    if target in app_actions:
        scope = "app"
    elif target in window_actions:
        scope = "window"
    else:
        return _result(
            operation,
            False,
            f"action {target!r} is not registered on app or window scope",
            error="unknown action",
            start=start,
        )
    args = [payload] if payload != "" else None
    saved = _activate_with_optional_save(bus, target, args, scope=scope, window_id=window_id)
    return _result(
        operation,
        True,
        f"activated {target!r} on {scope} scope",
        data={"action": target, "scope": scope, "payload": payload, "saved": saved},
        start=start,
    )


_ACTION_DESCRIPTIONS: dict[str, str] | None = None


def _load_action_descriptions(cli_executable: str = "inkscape") -> dict[str, str]:
    """Memoised parse of ``inkscape --action-list`` output. First call shells out
    to Inkscape (~150-300 ms); subsequent calls hit the in-memory cache.

    Returns ``{action_name: description}``. Empty dict if Inkscape isn't on PATH
    or the call times out — the annotated lists then degrade gracefully to
    name-only entries with empty descriptions.
    """
    import subprocess  # local import; only needed on first call

    global _ACTION_DESCRIPTIONS
    if _ACTION_DESCRIPTIONS is not None:
        return _ACTION_DESCRIPTIONS

    result: dict[str, str] = {}
    try:
        completed = subprocess.run(  # noqa: S603 — fixed `inkscape --action-list`, no user input
            [cli_executable, "--action-list"],
            capture_output=True,
            timeout=10,
            text=True,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        _ACTION_DESCRIPTIONS = result
        return result

    # Format: "name<padding>:  description"
    for line in completed.stdout.splitlines():
        if ":  " not in line:
            continue
        name, _, desc = line.partition(":  ")
        name = name.strip()
        if name:
            result[name] = desc.strip()
    _ACTION_DESCRIPTIONS = result
    return result


def _op_list_actions(
    bus: InkscapeDBus,
    operation: str,
    window_id: int,
    target: str,
    start: float,
) -> dict[str, Any]:
    """List all registered D-Bus actions, annotated with descriptions.

    ``target`` is an optional case-insensitive substring filter applied to both
    name and description. Use it to narrow the 1244-action surface (e.g.
    ``target="layer-"`` for layer ops, ``target="snap"`` for snap toggles).
    """
    descriptions = _load_action_descriptions()
    app_names = sorted(bus.list_actions("app"))
    window_names = sorted(bus.list_actions("window", window_id))

    def _annotate(names: list[str]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for n in names:
            # Fall back to the base name's description for the .noprefs variant —
            # Inkscape's --action-list reports only the base form for extensions.
            desc = descriptions.get(n)
            if desc is None and n.endswith(".noprefs"):
                desc = descriptions.get(n[: -len(".noprefs")], "")
            out.append({"name": n, "description": desc or ""})
        return out

    app = _annotate(app_names)
    window = _annotate(window_names)

    if target:
        needle = target.lower()

        def _match(item: dict[str, str]) -> bool:
            return needle in item["name"].lower() or needle in item["description"].lower()

        app = [a for a in app if _match(a)]
        window = [w for w in window if _match(w)]

    msg = f"{len(app)} app + {len(window)} window actions"
    if target:
        msg += f" matching {target!r}"
    return _result(
        operation,
        True,
        msg,
        data={"app": app, "window": window, "filter": target},
        start=start,
    )


def _op_open_file(bus: InkscapeDBus, operation: str, target: str, start: float) -> dict[str, Any]:
    if not target:
        return _result(operation, False, "target (file path) is required", error="missing target", start=start)
    if not os.path.isabs(target):
        return _result(
            operation,
            False,
            f"path must be absolute: {target!r}",
            error="relative path",
            start=start,
        )
    bus.open_file(target)
    return _result(operation, True, f"requested open of {target!r}", data={"path": target}, start=start)


_EDIT_XML_EXTENSION = "org.inkscape.mcp.edit-xml.noprefs"
_INSPECT_EXTENSION = "org.inkscape.mcp.inspect.noprefs"
_PATH_EDIT_EXTENSION = "org.inkscape.mcp.path-edit.noprefs"
_EXECUTE_EXTENSION = "org.inkscape.mcp.execute.noprefs"

_PATH_EDIT_OPS = frozenset(
    {
        "move_node",
        "set_handle_in",
        "set_handle_out",
        "insert_node",
        "smooth",
        "cusp",
        "subdivide",
    }
)


async def _do_inspect(
    bus: InkscapeDBus,
    category: str,
    operation: str,
    start: float,
    extra_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a single inspect category through the mcp_inspect extension.
    ``extra_spec`` adds category-specific fields (e.g. ``{"target": "<id>"}``
    for the ``element`` category)."""
    spec: dict[str, Any] = {"category": category}
    if extra_spec:
        spec.update(extra_spec)
    result = await invoke_extension(bus, _INSPECT_EXTENSION, spec, timeout_s=10.0)
    if not result.success:
        message = result.error or f"inspect '{category}' failed"
        if result.stderr:
            message = f"{message}\nstderr:\n{result.stderr}"
        return _result(
            operation,
            False,
            message,
            data={"category": category, "stderr": result.stderr},
            error=result.error,
            start=start,
        )

    # Honour an explicit ok:false from the extension (e.g. unknown category).
    if result.data.get("ok") is False:
        return _result(
            operation,
            False,
            result.data.get("error", "inspect failed"),
            data=result.data,
            error=result.data.get("error", ""),
            start=start,
        )

    summary = _inspect_summary(category, result.data)
    return _result(operation, True, summary, data=result.data, start=start)


def _inspect_summary(category: str, data: dict[str, Any]) -> str:
    if category == "selection":
        return f"{data.get('count', 0)} object(s) selected"
    if category == "layers":
        return f"{len(data.get('layers', []))} layer(s)"
    if category == "defs":
        counts = sum(
            len(data.get(k, []))
            for k in (
                "gradients",
                "filters",
                "markers",
                "patterns",
                "clip_paths",
                "masks",
                "symbols",
            )
        )
        return f"{counts} def(s) catalogued"
    if category == "view":
        return f"view: {data.get('viewbox', '?')}, zoom {data.get('zoom', '?')}"
    if category == "pages":
        return f"{data.get('count', 0)} page(s)"
    if category == "element":
        bbox = data.get("bbox") or {}
        return (
            f"<{data.get('tag', '?')}> id={data.get('id', '?')} "
            f"bbox=({bbox.get('x', '?')},{bbox.get('y', '?')},{bbox.get('w', '?')},{bbox.get('h', '?')})"
        )
    return f"inspect {category} succeeded"


async def _op_inspect_selection(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    return await _do_inspect(bus, "selection", operation, start)


async def _op_inspect_layers(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    return await _do_inspect(bus, "layers", operation, start)


async def _op_inspect_defs(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    return await _do_inspect(bus, "defs", operation, start)


async def _op_inspect_view(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    return await _do_inspect(bus, "view", operation, start)


async def _op_inspect_pages(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    return await _do_inspect(bus, "pages", operation, start)


async def _op_inspect_element(
    bus: InkscapeDBus,
    operation: str,
    target: str,
    start: float,
) -> dict[str, Any]:
    """Per-element analytical query: bbox + computed style + attributes + ancestor chain."""
    if not target:
        return _result(operation, False, "target (element id) is required", error="missing target", start=start)
    return await _do_inspect(bus, "element", operation, start, {"target": target})


async def _op_execute_inkex(
    bus: InkscapeDBus,
    operation: str,
    payload: str,
    start: float,
) -> dict[str, Any]:
    """Run arbitrary inkex Python via the mcp_execute extension.

    ``payload`` is the Python source as a raw string (NOT JSON-encoded). The
    extension exec()s it with ``svg``, ``inkex``, ``etree`` in scope and
    returns whatever the code assigns to ``result`` or returns from a
    ``main()`` function. Mutations to ``svg`` produce one ``MCP: Execute``
    undo entry; read-only code creates an ``[unchanged]`` entry.
    """
    if not payload or not payload.strip():
        return _result(
            operation,
            False,
            "payload (python code) is required",
            error="missing payload",
            start=start,
        )

    spec = {"python_code": payload}
    result = await invoke_extension(bus, _EXECUTE_EXTENSION, spec, timeout_s=30.0)

    if not result.success:
        message = result.error or "execute extension failed"
        if result.stderr:
            message = f"{message}\nstderr:\n{result.stderr}"
        return _result(
            operation,
            False,
            message,
            data={"stderr": result.stderr},
            error=result.error,
            start=start,
        )

    if result.data.get("ok") is False:
        err = result.data.get("error", "execute failed")
        tb = result.data.get("traceback", "")
        return _result(
            operation,
            False,
            f"{err}\n{tb}" if tb else err,
            data=result.data,
            error=err,
            start=start,
        )

    return _result(
        operation,
        True,
        f"executed {len(payload)} bytes of inkex code",
        data={"result": result.data.get("result")},
        start=start,
    )


def _op_rasterize(
    bus: InkscapeDBus,
    operation: str,
    target: str,
    payload: str,
    cli_wrapper: Any,
    config: Any,
    start: float,
) -> dict[str, Any]:
    """Render the current document (or a single element / area) to PNG.

    ``target`` — element id to render (uses ``--export-id``). Empty → full doc.
    ``payload`` — optional JSON: ``{"area": "x:y:w:h", "dpi": 96, "filename": "<abs>"}``.

    Saves a fresh snapshot of the live doc first so the export reflects
    in-memory state, then shells to Inkscape's CLI for the export. Returns
    the path to the produced PNG plus its byte size; the agent can read
    the file directly when it needs the pixels.
    """
    import json as _json
    import subprocess

    if cli_wrapper is None or config is None:
        return _result(
            operation,
            False,
            "rasterize requires cli_wrapper + config",
            error="missing dependencies",
            start=start,
        )

    args: dict[str, Any] = {}
    if payload:
        try:
            parsed = _json.loads(payload)
            if isinstance(parsed, dict):
                args = parsed
        except _json.JSONDecodeError as exc:
            return _result(operation, False, f"payload is not valid JSON: {exc}", error=str(exc), start=start)

    area = args.get("area")
    dpi = args.get("dpi")
    filename = args.get("filename")

    # Snapshot the live doc so the export reflects in-memory state.
    snapshot = _scratch_path()
    _export_document(bus, snapshot)

    # Choose output path.
    if filename:
        out_path = Path(filename)
        if not out_path.is_absolute():
            return _result(
                operation,
                False,
                f"filename must be absolute: {filename!r}",
                error="relative path",
                start=start,
            )
    else:
        out_path = _SCRATCH_DIR / f"raster-{uuid.uuid4().hex[:8]}.png"

    cmd = [
        str(config.inkscape_executable),
        "--app-id-tag=mcp",
        f"--export-filename={out_path}",
        "--export-type=png",
    ]
    if target:
        cmd.extend([f"--export-id={target}", "--export-id-only"])
    if area:
        if not isinstance(area, str) or area.count(":") != 3:
            return _result(
                operation,
                False,
                f"area must be 'x:y:w:h' (got {area!r})",
                error="bad area",
                start=start,
            )
        cmd.append(f"--export-area={area}")
    if dpi:
        try:
            cmd.append(f"--export-dpi={float(dpi)}")
        except (TypeError, ValueError):
            return _result(operation, False, f"dpi must be a number: {dpi!r}", error="bad dpi", start=start)
    cmd.append(str(snapshot))

    try:
        completed = subprocess.run(  # noqa: S603 — cmd is the inkscape executable + export flags built from validated args
            cmd,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _result(operation, False, "rasterize timed out after 60s", error="timeout", start=start)

    if completed.returncode != 0 or not out_path.exists():
        stderr_tail = (completed.stderr or b"").decode("utf-8", errors="replace")[-1000:]
        return _result(
            operation,
            False,
            f"inkscape export failed (rc={completed.returncode}); stderr: {stderr_tail}",
            data={"argv": cmd, "stderr": stderr_tail},
            error="export failed",
            start=start,
        )

    size = out_path.stat().st_size
    return _result(
        operation,
        True,
        f"rasterized to {out_path} ({size} bytes)",
        data={
            "path": str(out_path),
            "bytes": size,
            "target": target or None,
            "area": area,
            "dpi": dpi,
        },
        start=start,
    )


async def _op_edit_xml(
    bus: InkscapeDBus,
    operation: str,
    target_xpath: str,
    payload_json: str,
    window_id: int,
    start: float,
) -> dict[str, Any]:
    """Structural XML edit on the live document via the edit_xml inkex extension.

    Routing through an extension (rather than save → mutate-on-disk → revert)
    preserves Inkscape's undo history: each invocation registers as one
    undoable command.

    payload (JSON): {"action": "<verb>", ...action-args}
    actions:
      append/insert_before/insert_after/replace → require "xml" arg
      remove → no args
      set_attr → require "name", "value"
      set_text → require "text"
    """
    valid_actions = {
        "append",
        "insert_before",
        "insert_after",
        "remove",
        "set_attr",
        "set_text",
        "replace",
    }

    if not target_xpath:
        return _result(operation, False, "target (xpath) is required", error="missing target", start=start)
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError as exc:
        return _result(operation, False, f"payload is not valid JSON: {exc}", error=str(exc), start=start)
    if not isinstance(payload, dict):
        return _result(
            operation,
            False,
            "payload must decode to a JSON object",
            error="bad payload",
            start=start,
        )

    action = payload.get("action")
    if action not in valid_actions:
        return _result(
            operation,
            False,
            f"unknown action {action!r}; valid: {sorted(valid_actions)}",
            error="bad action",
            start=start,
        )

    # Spec shape: extension reads xpath/action and per-action keys merged from payload.
    spec: dict[str, Any] = {"xpath": target_xpath, "action": action}
    for key in ("xml", "name", "value", "text"):
        if key in payload:
            spec[key] = payload[key]

    result = await invoke_extension(bus, _EDIT_XML_EXTENSION, spec, timeout_s=15.0)

    if not result.success:
        message = result.error or "edit_xml extension failed"
        if result.stderr:
            message = f"{message}\nstderr:\n{result.stderr}"
        return _result(
            operation,
            False,
            message,
            data={"action": action, "xpath": target_xpath, "stderr": result.stderr},
            error=result.error,
            start=start,
        )

    # The extension reports its own outcome in the payload; a well-formed JSON body still
    # means success=True at the transport level. Without this check a bad XPath came back
    # as "affected 0 node(s)" with success=True — and we'd fire a pointless save on top.
    if result.data.get("ok") is False:
        return _result(
            operation,
            False,
            result.data.get("error", "edit_xml failed"),
            data={"action": action, "xpath": target_xpath, **result.data},
            error=result.data.get("error", ""),
            start=start,
        )

    # Persist the in-memory mutation to disk so re-reads see current state.
    # Honours the same kill switch as Pattern A: INKSCAPE_MCP_AUTO_SAVE=0 to skip.
    saved = False
    if os.environ.get(_AUTO_SAVE_ENV) != "0":
        try:
            bus.activate("document-save", scope="window", window_id=window_id)
            saved = True
        except Exception:  # noqa: S110 — save is best-effort; the primary mutation already succeeded
            pass

    affected = result.data.get("affected", 0)
    return _result(
        operation,
        True,
        f"edit_xml {action!r} affected {affected} node(s)",
        data={
            "action": action,
            "xpath": target_xpath,
            "affected": affected,
            "saved": saved,
            **{k: v for k, v in result.data.items() if k != "affected"},
        },
        start=start,
    )


async def _op_path_edit(
    bus: InkscapeDBus,
    operation: str,
    target: str,
    payload_json: str,
    window_id: int,
    start: float,
) -> dict[str, Any]:
    """Per-node bezier edits routed through the mcp_path_edit extension.

    ``target`` is the path element id. ``payload`` is JSON: ``{"op": "<sub-op>", ...}``
    with sub-op-specific fields (see plugins/mcp_path_edit.py docstring). Each
    invocation registers as one undoable "MCP: Path Edit" command.
    """
    if not target:
        return _result(operation, False, "target (path id) is required", error="missing target", start=start)
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError as exc:
        return _result(operation, False, f"payload is not valid JSON: {exc}", error=str(exc), start=start)
    if not isinstance(payload, dict):
        return _result(
            operation,
            False,
            "payload must decode to a JSON object",
            error="bad payload",
            start=start,
        )

    sub_op = payload.get("op")
    if sub_op not in _PATH_EDIT_OPS:
        return _result(
            operation,
            False,
            f"unknown path_edit op {sub_op!r}; valid: {sorted(_PATH_EDIT_OPS)}",
            error="bad op",
            start=start,
        )

    spec: dict[str, Any] = {"path_id": target}
    # Forward every payload key (op + per-op args). The extension validates
    # per-op required fields; we'd duplicate that validation by gating here.
    for key, value in payload.items():
        spec[key] = value

    result = await invoke_extension(bus, _PATH_EDIT_EXTENSION, spec, timeout_s=15.0)

    if not result.success:
        message = result.error or "path_edit extension failed"
        if result.stderr:
            message = f"{message}\nstderr:\n{result.stderr}"
        return _result(
            operation,
            False,
            message,
            data={"op": sub_op, "path_id": target, "stderr": result.stderr},
            error=result.error,
            start=start,
        )

    if result.data.get("ok") is False:
        return _result(
            operation,
            False,
            result.data.get("error", "path_edit failed"),
            data=result.data,
            error=result.data.get("error", ""),
            start=start,
        )

    saved = False
    if os.environ.get(_AUTO_SAVE_ENV) != "0":
        try:
            bus.activate("document-save", scope="window", window_id=window_id)
            saved = True
        except Exception:  # noqa: S110 — save is best-effort; the path edit already succeeded
            pass

    summary = result.data.get("summary", f"path_edit {sub_op!r} applied")
    return _result(
        operation,
        True,
        summary,
        data={
            "op": sub_op,
            "path_id": target,
            "saved": saved,
            **{k: v for k, v in result.data.items() if k not in ("ok", "op", "path_id")},
        },
        start=start,
    )


def _op_save_snapshot(bus: InkscapeDBus, operation: str, start: float) -> dict[str, Any]:
    scratch = _scratch_path()
    _export_document(bus, scratch)
    xml = scratch.read_text(encoding="utf-8")
    return _result(
        operation,
        True,
        f"snapshot written to {scratch}",
        data={"path": str(scratch), "xml": xml, "bytes": len(xml)},
        start=start,
    )


async def inkscape_live(
    operation: str,
    target: str = "",
    payload: str = "",
    window_id: int = 1,
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Drive a running Inkscape GUI via D-Bus + clipboard staging."""
    start = time.perf_counter()
    try:
        bus = _get_bus(config)
    except Exception as exc:
        return _result(
            operation,
            False,
            f"could not initialize live bridge: {exc}",
            error=str(exc),
            start=start,
        )

    # ping is the only op that must not raise when the bridge is down. ping reports
    # current state only — it never auto-launches Inkscape.
    if operation == "ping":
        try:
            return _op_ping(bus, operation, start)
        except Exception as exc:
            return _result(operation, False, f"ping failed: {exc}", error=str(exc), start=start)

    # Auto-manage (Windows): if the bridge isn't live yet, start the bus + Inkscape.
    if bus_manager.is_windows() and not bus.is_available():
        try:
            _auto_launch_inkscape(config)
        except Exception as exc:
            return _result(
                operation,
                False,
                f"auto-launch of Inkscape failed: {exc}",
                error=str(exc),
                start=start,
            )

    if not bus.is_available():
        return _result(
            operation,
            False,
            "Inkscape D-Bus bridge not reachable (is the GUI running?)",
            error="bridge unavailable",
            start=start,
        )

    # Auto-detect: if window 1 (or whatever was requested) isn't actually
    # open, fall back to the first available window. Lets the agent leave
    # the default and still work after the user closes/swaps documents.
    try:
        window_id = _resolve_window_id(bus, window_id)
    except RuntimeError as exc:
        return _result(operation, False, str(exc), error="no windows", start=start)

    try:
        if operation == "get_document_xml":
            return _op_get_document_xml(bus, operation, start)
        if operation == "get_selection":
            return await _op_get_selection(bus, operation, start)
        if operation == "set_selection":
            return _op_set_selection(bus, operation, target, start)
        if operation == "insert_svg":
            if bus_manager.is_windows():
                return await _op_insert_svg_via_inkex(bus, operation, payload, start)
            return _op_insert_svg(bus, operation, payload, window_id, start)
        if operation == "delete_selected":
            return _op_delete_selected(bus, operation, window_id, start)
        if operation == "apply_action":
            return _op_apply_action(bus, operation, target, payload, window_id, start)
        if operation == "list_actions":
            return _op_list_actions(bus, operation, window_id, target, start)
        if operation == "open_file":
            return _op_open_file(bus, operation, target, start)
        if operation == "save_snapshot":
            return _op_save_snapshot(bus, operation, start)
        if operation == "edit_xml":
            return await _op_edit_xml(bus, operation, target, payload, window_id, start)
        if operation == "path_edit":
            return await _op_path_edit(bus, operation, target, payload, window_id, start)
        if operation == "inspect_selection":
            return await _op_inspect_selection(bus, operation, start)
        if operation == "inspect_layers":
            return await _op_inspect_layers(bus, operation, start)
        if operation == "inspect_defs":
            return await _op_inspect_defs(bus, operation, start)
        if operation == "inspect_view":
            return await _op_inspect_view(bus, operation, start)
        if operation == "inspect_pages":
            return await _op_inspect_pages(bus, operation, start)
        if operation == "inspect_element":
            return await _op_inspect_element(bus, operation, target, start)
        if operation == "execute_inkex":
            return await _op_execute_inkex(bus, operation, payload, start)
        if operation == "rasterize":
            return _op_rasterize(bus, operation, target, payload, cli_wrapper, config, start)
        return _result(
            operation,
            False,
            f"unknown operation {operation!r}",
            error="unknown operation",
            start=start,
        )
    except Exception as exc:
        return _result(operation, False, f"{operation} failed: {exc}", error=str(exc), start=start)
