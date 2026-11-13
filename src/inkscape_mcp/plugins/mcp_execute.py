#!/usr/bin/env python3
"""mcp_execute — run arbitrary inkex Python against the live Inkscape document.

The broadest analytical and manipulation primitive in the MCP. Reads a string
of Python from ``input.json``, ``exec``s it with ``self.svg``, the ``inkex``
module, and ``lxml.etree`` already in scope, and serialises whatever the code
assigned to the local variable ``result`` (or returned from a ``main()``
function) to ``result.json``.

Reads ``~/.cache/inkscape_mcp/exchange/input.json``:

    {"python_code": "result = [el.get('id') for el in svg.iter() if el.tag.endswith('}path')]"}

Writes ``~/.cache/inkscape_mcp/exchange/result.json``:

    {"ok": True, "result": <whatever the code produced>}
    {"ok": False, "error": "<message>", "traceback": "<optional>"}

Mutation safety: if the code modifies ``svg`` (the in-memory document tree),
inkex's EffectExtension framework picks up the diff and creates one undoable
``MCP: Execute`` entry in Inkscape's history. Read-only code creates an
``[unchanged]`` undo entry (acceptable cost; see §0 gotcha 9 in the project
plan).

Globals provided to the executed code:

  svg     — the SVG root element (lxml-backed inkex element)
  doc     — alias for the same root
  inkex   — the full inkex module
  etree   — lxml.etree
  set_result(value) — convenience to assign to the result variable
  json    — stdlib json (handy for serialising data structures)
  math    — stdlib math

The executed code must produce a JSON-serialisable value. Non-serialisable
results (lxml elements, etc.) are coerced via ``str()``.

Security note: this runs arbitrary Python in Inkscape's process. The MCP
caller already has filesystem and shell access via Claude Code / similar
hosts; this extension does not add a new escalation path. It runs only when
invoked through the inkscape_mcp bridge by an authenticated local process.
"""

# Inkscape's AppImage ships Python 3.8: keep annotations lazy so PEP 585 generics
# like dict[str, Any] don't raise TypeError at import time.
from __future__ import annotations

import json
import math
import os
import traceback
from pathlib import Path

import inkex
from lxml import etree

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

# Cross-process isolation (see extension_bridge.py). The bridge addresses each spec
# to one plugin via `_plugin` and tags it with `_request_id`; we echo the id back.
_PLUGIN_NAME = "execute"
_REQUEST_ID = None


def _claim_spec():
    """Return the spec addressed to this plugin and consume it, or None if there is none.

    None means: no pending request (a late, queued duplicate of an invocation whose
    caller already gave up) or a request meant for another plugin. Either way the
    plugin must not touch the document or write a result.
    """
    global _REQUEST_ID
    src = EXCHANGE_DIR / "input.json"
    try:
        raw = src.read_text()
    except FileNotFoundError:
        return None
    spec = json.loads(raw)
    if isinstance(spec, dict):
        target = spec.get("_plugin")
        if target is not None and target != _PLUGIN_NAME:
            return None
        claimed = EXCHANGE_DIR / f".claimed-{_PLUGIN_NAME}-{os.getpid()}.json"
        try:
            os.replace(src, claimed)
        except FileNotFoundError:
            return None
        try:
            claimed.unlink()
        except OSError:
            pass
        _REQUEST_ID = spec.pop("_request_id", None)
        spec.pop("_plugin", None)
    return spec


def _write_result(payload: dict) -> None:
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    if _REQUEST_ID is not None:
        payload = {**payload, "_request_id": _REQUEST_ID}
    # Write-then-rename so the bridge never reads a half-written result.
    tmp = EXCHANGE_DIR / f".result-{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, default=str))
    os.replace(tmp, EXCHANGE_DIR / "result.json")


def _safe_serialise(value):
    """Best-effort JSON serialisation. lxml elements / inkex shapes coerce to
    repr; iterables of those coerce element-by-element; dicts get a
    one-level recursion."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(k): _safe_serialise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialise(v) for v in value]
    if hasattr(value, "tag"):
        # Looks like an element — return a small summary, not the whole tree.
        return {
            "_type": "element",
            "tag": str(value.tag),
            "id": value.get("id") if hasattr(value, "get") else None,
            "repr": repr(value),
        }
    return str(value)


class McpExecute(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = _claim_spec()
        except (OSError, json.JSONDecodeError) as exc:
            _write_result({"ok": False, "error": f"could not read input.json: {exc}"})
            return
        if spec is None:
            return

        if not isinstance(spec, dict):
            _write_result({"ok": False, "error": "input.json must decode to an object"})
            return

        code = spec.get("python_code")
        if not isinstance(code, str) or not code.strip():
            _write_result({"ok": False, "error": "'python_code' (non-empty string) is required"})
            return

        # self.svg is the SVG root in modern inkex.
        svg = self.svg.getroot() if hasattr(self.svg, "getroot") else self.svg

        scope: dict = {
            "__builtins__": __builtins__,
            "svg": svg,
            "doc": svg,
            "inkex": inkex,
            "etree": etree,
            "json": json,
            "math": math,
            "result": None,
        }

        def set_result(value):
            scope["result"] = value

        scope["set_result"] = set_result

        try:
            exec(compile(code, "<mcp_execute>", "exec"), scope, scope)  # noqa: S102 — exec is this extension's documented purpose; runs inkex code submitted via authenticated local MCP bridge
        except Exception as exc:
            _write_result(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            return

        # If the code defined a main() function, prefer its return value.
        if "main" in scope and callable(scope["main"]) and scope.get("result") is None:
            try:
                scope["result"] = scope["main"]()
            except Exception as exc:
                _write_result(
                    {
                        "ok": False,
                        "error": f"main() raised: {type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )
                return

        _write_result(
            {
                "ok": True,
                "result": _safe_serialise(scope.get("result")),
            }
        )


if __name__ == "__main__":
    try:
        McpExecute().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
