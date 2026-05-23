#!/usr/bin/env python3
"""mcp_echo — round-trip test fixture for the extension bridge.

Reads ~/.cache/inkscape_mcp/exchange/input.json, writes result.json with the
spec echoed back plus a coarse summary of the live document. Used by the MCP
to verify the bridge is alive end-to-end before invoking real extensions.
"""

import json
import os
import traceback
from pathlib import Path

import inkex

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))


class McpEcho(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = json.loads((EXCHANGE_DIR / "input.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _write_result({"ok": False, "error": f"could not read input.json: {exc}"})
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
    (EXCHANGE_DIR / "result.json").write_text(json.dumps(payload))


if __name__ == "__main__":
    try:
        McpEcho().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
