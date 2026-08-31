#!/usr/bin/env python3
"""mcp_path_edit — per-node bezier edits on a path in the live document.

EffectExtension that mutates a single ``<path>`` (identified by id) using
``inkex.paths`` math. Each invocation registers as one undoable command in
Inkscape's normal flow, preserving the user's undo history.

Reads ``~/.cache/inkscape_mcp/exchange/input.json``:

    {
        "path_id": "p1",
        "op":      "move_node|set_handle_in|set_handle_out|insert_node|smooth|cusp|subdivide",
        # per-op fields:
        "node":    [s, n],       # move_node, set_handle_*, smooth, cusp
        "to":      [x, y],       # move_node (new anchor pos), set_handle_* (new handle pos)
        "segment": [s, n],       # insert_node — split segment [n, n+1] on subpath s
        "t":       0.5,          # insert_node — parameter along the segment, 0..1
        "subpath": 0             # subdivide — optional; default subdivides every subpath
    }

Indexing model: ``s`` is the subpath index, ``n`` is the node index within
that subpath. Nodes in ``inkex.CubicSuperPath`` are ``[handle_in, anchor,
handle_out]`` triples; segments are determined by consecutive nodes.

Writes ``~/.cache/inkscape_mcp/exchange/result.json``:

    {"ok": True,  "op": ..., "path_id": ..., "d": "<new d>", "summary": "..."}
    {"ok": False, "error": "<message>"}
"""

import json
import math
import os
import traceback
from pathlib import Path

import inkex

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

_NODETYPES_ATTR = "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}nodetypes"

_VALID_OPS = frozenset(
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


def _write_result(payload: dict) -> None:
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    (EXCHANGE_DIR / "result.json").write_text(json.dumps(payload))


def _document_identity(root) -> dict:
    """Identify the document this extension ran against.

    Reports only what is knowable: `path` is set ONLY when `sodipodi:docname` is already
    absolute. Resolving a bare docname against the CWD would be wrong — an extension's
    CWD is the extension install directory, not the document's location.

    Duplicated in mcp_inspect.py: these plugins are copied into Inkscape's extension
    directory as standalone scripts, so they cannot share a module.
    """
    docname = root.get("{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname") or ""
    path = docname if docname.startswith("/") or (len(docname) > 2 and docname[1] == ":") else ""
    return {"docname": docname, "path": path, "root_id": root.get("id") or ""}


def _err(msg: str) -> None:
    _write_result({"ok": False, "error": msg})


def _xy(value, label: str):
    """Validate a 2-element numeric list/tuple. Raises ValueError on bad input."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be a 2-element [x, y] list")
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain numbers: {exc}") from None


def _node_index(value, label: str):
    """Validate a 2-element integer [s, n] list. Raises ValueError on bad input."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be a 2-element [s, n] list")
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain integers: {exc}") from None


def _flat_index(csp, s: int, n: int) -> int:
    """Convert (subpath, node) coordinates into a flat node index used by
    ``sodipodi:nodetypes``."""
    return sum(len(csp[i]) for i in range(s)) + n


def _ensure_nodetypes(element, csp) -> str:
    """Return the existing sodipodi:nodetypes string, padded/truncated to match
    the total node count. Defaults missing slots to 'c' (cusp)."""
    total = sum(len(sp) for sp in csp)
    raw = element.get(_NODETYPES_ATTR) or ""
    if len(raw) == total:
        return raw
    if len(raw) < total:
        return raw + "c" * (total - len(raw))
    return raw[:total]


def _set_nodetype(element, csp, s: int, n: int, kind: str) -> None:
    """Update sodipodi:nodetypes for the node at (s, n)."""
    raw = _ensure_nodetypes(element, csp)
    idx = _flat_index(csp, s, n)
    new_raw = raw[:idx] + kind + raw[idx + 1 :]
    element.set(_NODETYPES_ATTR, new_raw)


def _insert_nodetype(element, csp_before, s: int, n: int, kind: str) -> None:
    """Insert a new nodetype char after position (s, n) — for insert_node ops.
    Must be called BEFORE the csp is mutated so flat indices line up."""
    raw = _ensure_nodetypes(element, csp_before)
    idx = _flat_index(csp_before, s, n) + 1
    new_raw = raw[:idx] + kind + raw[idx:]
    element.set(_NODETYPES_ATTR, new_raw)


def _replace_subpath_nodetypes(element, csp_before, s: int, new_chars: str) -> None:
    """Replace the nodetype chars for subpath s wholesale — for subdivide ops.
    csp_before is the pre-mutation csp so flat indices are correct."""
    raw = _ensure_nodetypes(element, csp_before)
    start = _flat_index(csp_before, s, 0)
    end = start + len(csp_before[s])
    element.set(_NODETYPES_ATTR, raw[:start] + new_chars + raw[end:])


def _split_cubic(p0, p1, p2, p3, t: float):
    """De Casteljau split of the cubic [p0, p1, p2, p3] at parameter t.
    Returns (q0, r0, s_point, r1, q2) where the split point is s_point and the
    two halves have control polygons [p0, q0, r0, s_point] and
    [s_point, r1, q2, p3]."""

    def lerp(a, b):
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]

    q0 = lerp(p0, p1)
    q1 = lerp(p1, p2)
    q2 = lerp(p2, p3)
    r0 = lerp(q0, q1)
    r1 = lerp(q1, q2)
    s_point = lerp(r0, r1)
    return q0, r0, s_point, r1, q2


def _do_move_node(csp, spec):
    s, n = _node_index(spec.get("node"), "node")
    to = _xy(spec.get("to"), "to")
    if not (0 <= s < len(csp)) or not (0 <= n < len(csp[s])):
        raise ValueError(f"node ({s}, {n}) out of range")
    hi, anchor, ho = csp[s][n]
    dx, dy = to[0] - anchor[0], to[1] - anchor[1]
    csp[s][n] = [
        [hi[0] + dx, hi[1] + dy],
        [to[0], to[1]],
        [ho[0] + dx, ho[1] + dy],
    ]
    return f"moved node ({s},{n}) by ({dx:.3f},{dy:.3f})"


def _do_set_handle(csp, spec, side: str):
    s, n = _node_index(spec.get("node"), "node")
    to = _xy(spec.get("to"), "to")
    if not (0 <= s < len(csp)) or not (0 <= n < len(csp[s])):
        raise ValueError(f"node ({s}, {n}) out of range")
    if side == "in":
        csp[s][n][0] = [to[0], to[1]]
    else:
        csp[s][n][2] = [to[0], to[1]]
    return f"set handle_{side} of node ({s},{n}) to ({to[0]:.3f},{to[1]:.3f})"


def _do_insert_node(element, csp, spec):
    s, n = _node_index(spec.get("segment"), "segment")
    try:
        t = float(spec.get("t", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"t must be a number: {exc}") from None
    if not (0.0 < t < 1.0):
        raise ValueError(f"t must be strictly between 0 and 1, got {t}")
    if not (0 <= s < len(csp)) or not (0 <= n < len(csp[s]) - 1):
        raise ValueError(f"segment ({s}, {n}) out of range (need n < len(subpath)-1)")

    a_hi, a_anchor, a_ho = csp[s][n]
    b_hi, b_anchor, b_ho = csp[s][n + 1]
    q0, r0, sp, r1, q2 = _split_cubic(a_anchor, a_ho, b_hi, b_anchor, t)

    # Nodetypes index correction must happen BEFORE csp mutation.
    _insert_nodetype(element, csp, s, n, "s")

    csp[s][n] = [a_hi, a_anchor, q0]
    csp[s].insert(n + 1, [r0, sp, r1])
    csp[s][n + 2] = [q2, b_anchor, b_ho]
    return f"inserted node on subpath {s} between {n} and {n + 1} at t={t}"


def _do_smooth(element, csp, spec):
    s, n = _node_index(spec.get("node"), "node")
    if not (0 <= s < len(csp)) or not (0 <= n < len(csp[s])):
        raise ValueError(f"node ({s}, {n}) out of range")
    hi, anchor, ho = csp[s][n]
    off_in = [hi[0] - anchor[0], hi[1] - anchor[1]]
    off_out = [ho[0] - anchor[0], ho[1] - anchor[1]]
    len_in = math.hypot(*off_in)
    len_out = math.hypot(*off_out)

    direction = [off_out[0] - off_in[0], off_out[1] - off_in[1]]
    norm = math.hypot(*direction)
    if norm > 1e-9:
        unit = [direction[0] / norm, direction[1] / norm]
        if len_in > 1e-9:
            csp[s][n][0] = [anchor[0] - unit[0] * len_in, anchor[1] - unit[1] * len_in]
        if len_out > 1e-9:
            csp[s][n][2] = [anchor[0] + unit[0] * len_out, anchor[1] + unit[1] * len_out]
    _set_nodetype(element, csp, s, n, "s")
    return f"smoothed node ({s},{n})"


def _do_cusp(element, csp, spec):
    s, n = _node_index(spec.get("node"), "node")
    if not (0 <= s < len(csp)) or not (0 <= n < len(csp[s])):
        raise ValueError(f"node ({s}, {n}) out of range")
    _set_nodetype(element, csp, s, n, "c")
    return f"marked node ({s},{n}) as cusp"


def _do_subdivide(element, csp, spec):
    target = spec.get("subpath")
    if target is None:
        indices = list(range(len(csp)))
    else:
        try:
            indices = [int(target)]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"subpath must be an integer: {exc}") from None
        if not (0 <= indices[0] < len(csp)):
            raise ValueError(f"subpath {indices[0]} out of range")

    inserted = 0
    # Subdivide each subpath in reverse index order so earlier indices stay
    # valid as we rewrite later subpaths' nodetype chunks.
    for s in sorted(indices, reverse=True):
        old = csp[s]
        if len(old) < 2:
            continue
        new_sub = [old[0]]
        new_chars = "c"
        for n in range(len(old) - 1):
            _a_hi, a_anchor, a_ho = old[n]
            b_hi, b_anchor, b_ho = old[n + 1]
            q0, r0, sp, r1, q2 = _split_cubic(a_anchor, a_ho, b_hi, b_anchor, 0.5)
            # Patch the *previous* node's out-handle in the new subpath.
            new_sub[-1] = [new_sub[-1][0], new_sub[-1][1], q0]
            new_sub.append([r0, sp, r1])
            new_sub.append([q2, b_anchor, b_ho])
            new_chars += "sc"
            inserted += 1
        # Replace nodetype chunk for this subpath (pre-mutation csp still valid here).
        _replace_subpath_nodetypes(element, csp, s, new_chars)
        csp[s] = new_sub
    return f"subdivided {inserted} segment(s)"


class McpPathEdit(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = json.loads((EXCHANGE_DIR / "input.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _err(f"could not read input.json: {exc}")
            return

        if not isinstance(spec, dict):
            _err("input.json must decode to an object")
            return

        path_id = spec.get("path_id")
        if not path_id or not isinstance(path_id, str):
            _err("'path_id' is required")
            return

        op = spec.get("op")
        if op not in _VALID_OPS:
            _err(f"unknown op {op!r}; valid: {sorted(_VALID_OPS)}")
            return

        element = self.svg.getElementById(path_id)
        if element is None:
            _err(f"no element with id {path_id!r}")
            return

        # Accept any element carrying a `d` attribute — paths, but also
        # shapes that have been converted. inkex.PathElement is the typical
        # case; we fall back to attribute reading if `.path` isn't usable.
        if not isinstance(element, inkex.PathElement):
            _err(f"element {path_id!r} is not a <path> (got {element.tag})")
            return

        try:
            csp = element.path.to_superpath()
        except Exception as exc:
            _err(f"could not parse path 'd': {exc}")
            return

        try:
            if op == "move_node":
                summary = _do_move_node(csp, spec)
            elif op == "set_handle_in":
                summary = _do_set_handle(csp, spec, "in")
            elif op == "set_handle_out":
                summary = _do_set_handle(csp, spec, "out")
            elif op == "insert_node":
                summary = _do_insert_node(element, csp, spec)
            elif op == "smooth":
                summary = _do_smooth(element, csp, spec)
            elif op == "cusp":
                summary = _do_cusp(element, csp, spec)
            elif op == "subdivide":
                summary = _do_subdivide(element, csp, spec)
            else:
                _err(f"op {op!r} not implemented")
                return
        except ValueError as exc:
            _err(str(exc))
            return

        new_d = str(inkex.Path(csp))
        element.set("d", new_d)

        # Name the document that was actually mutated — Inkscape runs effects against
        # the ACTIVE desktop and offers no way to pick another.
        svg_root = self.svg.getroot() if hasattr(self.svg, "getroot") else self.svg
        _write_result(
            {
                "ok": True,
                "op": op,
                "path_id": path_id,
                "d": new_d,
                "summary": summary,
                "active_document": _document_identity(svg_root),
            }
        )


if __name__ == "__main__":
    try:
        McpPathEdit().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
