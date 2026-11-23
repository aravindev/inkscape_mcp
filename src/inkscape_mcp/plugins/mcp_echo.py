#!/usr/bin/env python3
"""mcp_echo — round-trip test fixture for the extension bridge.

Reads ~/.cache/inkscape_mcp/exchange/input.json, writes result.json with the
spec echoed back plus a coarse summary of the live document. Used by the MCP
to verify the bridge is alive end-to-end before invoking real extensions.
"""

# Inkscape's AppImage ships Python 3.8: keep annotations lazy so PEP 585 generics
# like dict[str, Any] don't raise TypeError at import time.
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import inkex

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

# Cross-process isolation (see extension_bridge.py). The bridge addresses each spec
# to one plugin via `_plugin` and tags it with `_request_id`; we echo the id back.
_PLUGIN_NAME = "echo"
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


class McpEcho(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = _claim_spec()
        except (OSError, json.JSONDecodeError) as exc:
            _write_result({"ok": False, "error": f"could not read input.json: {exc}"})
            return
        if spec is None:
            return

        root = self.svg.getroot() if hasattr(self.svg, "getroot") else self.svg

        mutations_applied = 0
        mutate = spec.get("mutate")
        if isinstance(mutate, dict):
            set_attr = mutate.get("set_attr")
            if isinstance(set_attr, dict):
                target_id = set_attr.get("id")
                name = set_attr.get("name")
                value = set_attr.get("value", "")
                target = self.svg.getElementById(target_id) if target_id else None
                if target is not None and name:
                    target.set(name, str(value))
                    mutations_applied += 1

        n_elements = sum(1 for _ in root.iter())
        result = {
            "ok": True,
            "echoed": spec,
            "doc": {"root_tag": root.tag, "elements": n_elements},
            "mutations_applied": mutations_applied,
        }
        _write_result(result)


def _write_result(payload: dict) -> None:
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    if _REQUEST_ID is not None:
        payload = {**payload, "_request_id": _REQUEST_ID}
    # Write-then-rename so the bridge never reads a half-written result.
    tmp = EXCHANGE_DIR / f".result-{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, EXCHANGE_DIR / "result.json")


if __name__ == "__main__":
    try:
        McpEcho().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
