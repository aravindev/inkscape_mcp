"""Inkscape extension runner — discover and invoke any installed extension.

Most of Inkscape's feature surface ships as `inkex`-based extensions. Their
``.noprefs`` D-Bus actions only fire with default parameter values; this tool
exposes the full parameter surface by invoking the extension's Python script
directly as a subprocess (the same protocol Inkscape uses internally).

Surfaces:

- ``list`` — discover all installed extensions (system + user dirs).
- ``describe`` — return the full INX-declared param schema for one extension.
- ``run`` — execute headless on an input file, write the result to disk.
- ``run_live`` — fire on the open Inkscape document. With empty params,
  routes via D-Bus ``apply_action(.noprefs)`` (preserves undo). With params,
  saves the doc → runs headless → reverts (wipes undo, documented trade-off).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from .live import _get_bus, _result

_SYSTEM_EXT_DIRS = (
    Path("/usr/share/inkscape/extensions"),
    Path("/usr/local/share/inkscape/extensions"),
)
_USER_EXT_DIR = Path(os.path.expanduser("~/.config/inkscape/extensions"))

# How long to wait for an extension subprocess. Some (LaTeX renderers, raster
# filters) are genuinely slow; cap generously.
_EXT_TIMEOUT_S = 120.0


@dataclass
class _ExtensionParam:
    name: str
    type: str
    default: Any = None
    description: str = ""
    options: list[str] = field(default_factory=list)


@dataclass
class _Extension:
    id: str
    name: str
    inx_path: Path
    script_path: Path | None  # None for non-Python extensions
    interpreter: str
    params: list[_ExtensionParam]
    category: str
    source: str  # "system" | "user"


_CACHE: dict[str, _Extension] | None = None


def _all_ext_dirs() -> list[Path]:
    return [*_SYSTEM_EXT_DIRS, _USER_EXT_DIR]


def _parse_inx(inx_path: Path, source: str) -> _Extension | None:
    """Parse an INX file into our internal representation. Tolerant of malformed
    files — returns None on parse error rather than raising."""
    try:
        tree = etree.parse(str(inx_path))
    except (etree.XMLSyntaxError, OSError):
        return None
    root = tree.getroot()
    ns = "{http://www.inkscape.org/namespace/inkscape/extension}"

    def _text(tag: str) -> str:
        el = root.find(f"{ns}{tag}")
        return (el.text or "").strip() if el is not None else ""

    ext_id = _text("id")
    if not ext_id:
        return None
    name = _text("name") or ext_id

    interpreter = ""
    script_path: Path | None = None
    cmd_el = root.find(f"{ns}script/{ns}command")
    if cmd_el is not None:
        interpreter = (cmd_el.get("interpreter") or "").strip()
        script_name = (cmd_el.text or "").strip()
        location = (cmd_el.get("location") or "inx").strip()
        if script_name:
            if location == "inx":
                script_path = (inx_path.parent / script_name).resolve()
            else:
                script_path = Path(script_name)

    params: list[_ExtensionParam] = []
    for param_el in root.findall(f".//{ns}param"):
        param_name = param_el.get("name")
        if not param_name:
            continue
        param_type = (param_el.get("type") or "string").strip()
        default = (param_el.text or "").strip()
        description = (param_el.get("gui-text") or "").strip()
        options: list[str] = []
        if param_type == "optiongroup" or param_type == "enum":
            for opt in param_el.findall(f"{ns}option"):
                value = opt.get("value")
                if value:
                    options.append(value)
        params.append(
            _ExtensionParam(
                name=param_name,
                type=param_type,
                default=default,
                description=description,
                options=options,
            )
        )

    category = ""
    submenu_el = root.find(f".//{ns}effects-menu/{ns}submenu")
    if submenu_el is not None and submenu_el.text:
        category = submenu_el.text.strip()

    return _Extension(
        id=ext_id,
        name=name,
        inx_path=inx_path,
        script_path=script_path,
        interpreter=interpreter,
        params=params,
        category=category,
        source=source,
    )


def _discover(refresh: bool = False) -> dict[str, _Extension]:
    """Build (or return cached) {ext_id: _Extension} map by scanning the standard
    extension dirs. User-dir entries override system ones with the same id."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    found: dict[str, _Extension] = {}
    for source_label, ext_dir in (
        ("system", _SYSTEM_EXT_DIRS[0]),
        ("system", _SYSTEM_EXT_DIRS[1]),
        ("user", _USER_EXT_DIR),
    ):
        if not ext_dir.is_dir():
            continue
        for inx_path in ext_dir.glob("*.inx"):
            ext = _parse_inx(inx_path, source_label)
            if ext is not None:
                found[ext.id] = ext  # later wins (user > system)
    _CACHE = found
    return found


def _format_param_arg(param: _ExtensionParam, value: Any) -> str:
    """Render a single --name=value flag for the inkex subprocess. Inkex
    extensions parse with argparse using underscores in arg names but inx
    declarations also use underscores — pass through verbatim."""
    if param.type == "boolean" or param.type == "bool":
        # inkex expects literal "true"/"false" for boolean params.
        value = "true" if value in (True, "true", "True", 1, "1") else "false"
    return f"--{param.name}={value}"


def _build_command(ext: _Extension, params: dict[str, Any], input_path: Path) -> list[str]:
    """Build the subprocess argv for invoking an inkex extension headlessly."""
    if ext.script_path is None:
        raise ValueError(f"extension {ext.id!r} has no script command")
    interpreter = ext.interpreter or "python"
    if interpreter == "python":
        interpreter = sys.executable  # use our resolved Python
    argv: list[str] = [interpreter, str(ext.script_path)]
    known = {p.name: p for p in ext.params}
    for key, val in params.items():
        if key in known:
            argv.append(_format_param_arg(known[key], val))
        else:
            # Pass-through for params we didn't see in the INX (some extensions
            # accept undeclared flags). Caller takes responsibility.
            argv.append(f"--{key}={val}")
    argv.append(str(input_path))
    return argv


async def _run_subprocess(argv: list[str], cwd: Path | None) -> tuple[bool, bytes, str]:
    """Run an extension subprocess. Returns (success, stdout_bytes, stderr_text)."""
    env = os.environ.copy()
    # inkex extensions import inkex; make sure both the bundled and pip-installed
    # paths are reachable. cwd handles the bundled case (relative imports).
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_EXT_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return False, b"", f"extension timed out after {_EXT_TIMEOUT_S}s"
    if proc.returncode != 0:
        return False, stdout or b"", (stderr or b"").decode("utf-8", errors="replace")
    return True, stdout or b"", (stderr or b"").decode("utf-8", errors="replace")


def _ext_summary(ext: _Extension) -> dict[str, Any]:
    return {
        "id": ext.id,
        "name": ext.name,
        "category": ext.category,
        "source": ext.source,
        "interpreter": ext.interpreter,
        "params": [p.name for p in ext.params],
    }


def _ext_describe(ext: _Extension) -> dict[str, Any]:
    return {
        "id": ext.id,
        "name": ext.name,
        "category": ext.category,
        "source": ext.source,
        "interpreter": ext.interpreter,
        "inx_path": str(ext.inx_path),
        "script_path": str(ext.script_path) if ext.script_path else None,
        "params": [
            {
                "name": p.name,
                "type": p.type,
                "default": p.default,
                "description": p.description,
                "options": p.options,
            }
            for p in ext.params
        ],
    }


def _op_list(operation: str, target: str, start: float) -> dict[str, Any]:
    catalog = _discover()
    items = [_ext_summary(ext) for ext in catalog.values()]
    if target:
        prefix = target.lower()
        items = [
            it
            for it in items
            if prefix in it["id"].lower() or prefix in it["name"].lower() or prefix in it["category"].lower()
        ]
    items.sort(key=lambda it: it["id"])
    return _result(
        operation,
        True,
        f"{len(items)} extension(s) discovered",
        data={"extensions": items, "filter": target},
        start=start,
    )


def _op_describe(operation: str, target: str, start: float) -> dict[str, Any]:
    if not target:
        return _result(
            operation,
            False,
            "target (extension id) is required",
            error="missing target",
            start=start,
        )
    catalog = _discover()
    ext = catalog.get(target)
    if ext is None:
        return _result(
            operation,
            False,
            f"no extension with id {target!r}",
            data={"available_hint": [e.id for e in list(catalog.values())[:10]]},
            error="unknown extension",
            start=start,
        )
    return _result(operation, True, f"described {ext.id}", data=_ext_describe(ext), start=start)


async def _op_run(
    operation: str,
    target: str,
    params: dict[str, Any],
    input_path: str,
    output_path: str,
    start: float,
) -> dict[str, Any]:
    if not target:
        return _result(
            operation,
            False,
            "target (extension id) is required",
            error="missing target",
            start=start,
        )
    if not input_path:
        return _result(
            operation,
            False,
            "input_path is required for run",
            error="missing input_path",
            start=start,
        )

    input_p = Path(input_path)
    if not input_p.is_absolute():
        return _result(
            operation,
            False,
            f"input_path must be absolute: {input_path!r}",
            error="relative path",
            start=start,
        )
    if not input_p.is_file():
        return _result(
            operation,
            False,
            f"input_path does not exist: {input_path!r}",
            error="missing input",
            start=start,
        )

    out_p = Path(output_path) if output_path else input_p
    if not out_p.is_absolute():
        return _result(
            operation,
            False,
            f"output_path must be absolute: {output_path!r}",
            error="relative path",
            start=start,
        )

    catalog = _discover()
    ext = catalog.get(target)
    if ext is None:
        return _result(
            operation,
            False,
            f"no extension with id {target!r}",
            error="unknown extension",
            start=start,
        )
    if ext.script_path is None:
        return _result(
            operation,
            False,
            f"extension {target!r} has no Python script command — non-script extensions are not supported",
            error="unsupported extension",
            start=start,
        )

    try:
        argv = _build_command(ext, params, input_p)
    except ValueError as exc:
        return _result(operation, False, str(exc), error=str(exc), start=start)

    ok, stdout, stderr = await _run_subprocess(argv, cwd=ext.script_path.parent)
    if not ok:
        return _result(
            operation,
            False,
            f"extension failed (rc != 0); stderr:\n{stderr[:2000]}",
            data={"argv": argv, "stderr": stderr},
            error=stderr.splitlines()[-1] if stderr else "extension failed",
            start=start,
        )

    if not stdout:
        return _result(
            operation,
            False,
            "extension produced no stdout — unexpected for an inkex Effect/Filter extension",
            data={"argv": argv, "stderr": stderr},
            error="empty output",
            start=start,
        )

    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(stdout)
    except OSError as exc:
        return _result(operation, False, f"could not write output: {exc}", error=str(exc), start=start)

    return _result(
        operation,
        True,
        f"ran {ext.id} ({len(stdout)} bytes → {out_p})",
        data={
            "id": ext.id,
            "input_path": str(input_p),
            "output_path": str(out_p),
            "bytes": len(stdout),
            "stderr": stderr,
        },
        start=start,
    )


_EMPTY_CANVAS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
    'viewBox="0 0 1000 1000" width="1000" height="1000"/>'
)


def _extract_extension_output(output_xml: str, wrapper_id: str) -> str:
    """Take the extension's output SVG (which started from an empty canvas) and
    return a serialized ``<g>`` wrapping every child of its root.

    Why this works: the canvas was empty, so every child of the output's root
    is by definition new content produced by the extension. Wrapping them in
    one group means a single ``append`` mutation on the live doc — one undo
    entry, no diffing, no positional xpath shenanigans.

    ``<defs>`` / ``<symbol>`` children get pulled inside the wrapper too; SVG's
    id-based ``<use href="#x">`` resolution still finds them via document-wide
    id lookup, so the result renders identically.
    """
    output_tree = etree.fromstring(output_xml.encode("utf-8"))
    SVG_NS = "http://www.w3.org/2000/svg"
    INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

    wrapper = etree.Element(
        f"{{{SVG_NS}}}g",
        nsmap={
            None: SVG_NS,
            "xlink": "http://www.w3.org/1999/xlink",
            "inkscape": INKSCAPE_NS,
        },
    )
    wrapper.set("id", wrapper_id)
    wrapper.set(f"{{{INKSCAPE_NS}}}label", "MCP extension output")
    for child in list(output_tree):
        wrapper.append(child)
    return etree.tostring(wrapper, encoding="unicode")


_WRAPPER_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


async def _op_run_live(
    operation: str,
    target: str,
    params: dict[str, Any],
    requested_wrapper_id: str,
    start: float,
) -> dict[str, Any]:
    """Apply an extension to the running Inkscape document.

    Two paths:
      - **No params** → fire ``apply_action(<id>.noprefs)`` via D-Bus. One undo
        entry on the live doc (Inkscape's native pathway).
      - **With params** → render the extension on an **empty canvas** headlessly,
        wrap its output in a ``<g id="mcp-ext-…">``, and append that wrapper to
        the live ``<svg>`` root via a single ``mcp_edit_xml`` call. One
        ``MCP: Edit`` undo entry; no diffing of the user's existing content.

    ``requested_wrapper_id`` — optional. When provided, the wrapper uses that
    id instead of a freshly-generated ``mcp-ext-<hex>``, and any existing
    element with the same id is removed first. Use this to **re-render in
    place**: any CSS rules / style hooks that referenced the previous wrapper
    keep applying because the id is preserved.

    The render-on-empty-canvas approach only suits *generator* extensions
    (pdflatex, calendar, barcode, qr, gears, polyhedra, etc.). Transformer
    extensions (filters, color shifts, ungroup) need existing content to act
    on — running them on an empty canvas produces empty output; use the
    no-params D-Bus path or run them headlessly via ``run`` instead.
    """
    if not target:
        return _result(
            operation,
            False,
            "target (extension id) is required",
            error="missing target",
            start=start,
        )

    bus = _get_bus()
    if not bus.is_available():
        return _result(
            operation,
            False,
            "Inkscape D-Bus bridge unavailable (is the GUI running?)",
            error="bridge unavailable",
            start=start,
        )

    if not params:
        action_name = f"{target}.noprefs"
        registered = set(bus.list_actions("app")) | set(bus.list_actions("window"))
        if action_name not in registered:
            return _result(
                operation,
                False,
                f"no D-Bus action {action_name!r} (extension might not be installed or might need a restart)",
                error="action not registered",
                start=start,
            )
        scope = "app" if action_name in bus.list_actions("app") else "window"
        # Auto-detect window when scope is "window" — picks the first open
        # window if 1 isn't actually present.
        from .live import _resolve_window_id

        win = _resolve_window_id(bus, 1) if scope == "window" else 1
        bus.activate(action_name, scope=scope, window_id=win)
        return _result(
            operation,
            True,
            f"fired {action_name} on {scope} scope (undo-preserving)",
            data={"id": target, "mode": "noprefs", "scope": scope, "undo_preserved": True},
            start=start,
        )

    # Params provided → render-on-empty-canvas route.
    import uuid as _uuid

    from ..extension_bridge import invoke_extension
    from .live import (
        _EDIT_XML_EXTENSION,  # local import to avoid cycle
        _scratch_path,  # local import to avoid cycle
    )

    # Validate / resolve the wrapper id.
    if requested_wrapper_id:
        if not _WRAPPER_ID_RE.match(requested_wrapper_id):
            return _result(
                operation,
                False,
                f"wrapper_id must match {_WRAPPER_ID_RE.pattern!r}; got {requested_wrapper_id!r}",
                error="invalid wrapper_id",
                start=start,
            )
        wrapper_id = requested_wrapper_id
    else:
        wrapper_id = f"mcp-ext-{_uuid.uuid4().hex[:8]}"

    # If caller supplied an id, pre-remove any existing element with that id
    # so we can write the fresh wrapper in its place. Tolerate the
    # "not found" case — the id simply hasn't been used yet.
    replaced_existing = False
    if requested_wrapper_id:
        remove_spec = {"xpath": f"//*[@id={wrapper_id!r}]", "action": "remove"}
        rm_res = await invoke_extension(bus, _EDIT_XML_EXTENSION, remove_spec, timeout_s=10.0)
        if rm_res.success and rm_res.data.get("ok") is True:
            replaced_existing = True
        # If remove failed because the id wasn't present, mcp_edit_xml returns
        # ok:false with "xpath matched no nodes" — that's fine, just continue.

    scratch = _scratch_path()
    scratch.write_text(_EMPTY_CANVAS, encoding="utf-8")

    res = await _op_run(operation, target, params, str(scratch), str(scratch), start)
    if not res["success"]:
        return res

    output_xml = scratch.read_text(encoding="utf-8")
    try:
        wrapper_xml = _extract_extension_output(output_xml, wrapper_id)
    except etree.XMLSyntaxError as exc:
        return _result(
            operation,
            False,
            f"could not parse extension output: {exc}",
            data={"output_path": str(scratch), "id": target},
            error=str(exc),
            start=start,
        )

    # Empty wrapper → extension produced nothing usable for a generator pass.
    # Most likely a transformer extension that needs existing content.
    parsed_wrapper = etree.fromstring(wrapper_xml.encode("utf-8"))
    if len(parsed_wrapper) == 0:
        return _result(
            operation,
            False,
            f"{target} produced no content on an empty canvas — likely a "
            "transformer extension (needs existing elements). Try the no-params "
            "D-Bus path or the headless 'run' operation on a real file.",
            data={"id": target, "output_path": str(scratch)},
            error="empty output",
            start=start,
        )

    apply_spec = {
        "xpath": "/svg:svg",
        "action": "append",
        "xml": wrapper_xml,
    }
    result = await invoke_extension(bus, _EDIT_XML_EXTENSION, apply_spec, timeout_s=15.0)
    if not result.success or result.data.get("ok") is False:
        msg = result.error or result.data.get("error", "edit_xml apply failed")
        if result.stderr:
            msg = f"{msg}\nstderr:\n{result.stderr}"
        return _result(
            operation,
            False,
            f"rendered {target} but couldn't merge into live doc: {msg}",
            data={
                "id": target,
                "wrapper_id": wrapper_id,
                "wrapper_xml": wrapper_xml[:2000],
                "output_path": str(scratch),
            },
            error=result.error or "merge failed",
            start=start,
        )

    if replaced_existing:
        msg = (
            f"replaced existing <g id='{wrapper_id}'> with fresh render of {target} "
            "(two MCP: Edit undo entries: remove + append)"
        )
    else:
        msg = f"rendered {target} → appended as <g id='{wrapper_id}'> (one MCP: Edit undo entry)"
    return _result(
        operation,
        True,
        msg,
        data={
            "id": target,
            "mode": "render-and-merge",
            "wrapper_id": wrapper_id,
            "replaced_existing": replaced_existing,
            "undo_preserved": True,
            "output_path": str(scratch),
        },
        start=start,
    )


async def inkscape_extension(
    operation: str,
    target: str = "",
    params: str = "",
    input_path: str = "",
    output_path: str = "",
    wrapper_id: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Discover, describe, and invoke any installed Inkscape extension.

    Operations:
      list        — discover all extensions; ``target`` filters by substring (id/name/category)
      describe    — show full param schema for one extension (``target`` = extension id)
      run         — invoke headlessly on a file (``target`` + ``params`` JSON +
                    ``input_path`` + optional ``output_path``)
      run_live    — invoke on the running Inkscape doc (``target`` + ``params``). Empty params route
                    via D-Bus and preserve undo. Provided params render on an empty canvas and
                    append the output wrapped in `<g id="mcp-ext-…">`. Pass ``wrapper_id`` to
                    re-render in place — any prior element with that id is removed first, so CSS
                    rules / style hooks targeting the id keep applying.
    """
    start = time.perf_counter()

    parsed_params: dict[str, Any] = {}
    if params:
        try:
            parsed = json.loads(params)
            if not isinstance(parsed, dict):
                return _result(
                    operation,
                    False,
                    "params must be a JSON object",
                    error="bad params",
                    start=start,
                )
            parsed_params = parsed
        except json.JSONDecodeError as exc:
            return _result(operation, False, f"params is not valid JSON: {exc}", error=str(exc), start=start)

    try:
        if operation == "list":
            return _op_list(operation, target, start)
        if operation == "describe":
            return _op_describe(operation, target, start)
        if operation == "run":
            return await _op_run(operation, target, parsed_params, input_path, output_path, start)
        if operation == "run_live":
            return await _op_run_live(operation, target, parsed_params, wrapper_id, start)
        return _result(
            operation,
            False,
            f"unknown operation {operation!r}",
            error="unknown operation",
            start=start,
        )
    except Exception as exc:
        return _result(operation, False, f"{operation} failed: {exc}", error=str(exc), start=start)
