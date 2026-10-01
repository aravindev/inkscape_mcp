"""Layer management for Inkscape SVG documents.

Operations: list, get, create, rename, delete, show, hide, lock, unlock, reorder.

The operation set and the idea of treating layers as plain ``<g inkscape:groupmode="layer">``
elements come from sandraschi/inkscape-mcp (MIT); see NOTICE.md. This is a reimplementation on a
real XML tree rather than regular expressions over the file text, which fixes several problems of
the text approach: a layer containing groups or sublayers broke the match (non-greedy ``</g>``),
labels were written unescaped (a ``"`` corrupted the file), a tag was replaced everywhere it
occurred, and ``reorder`` relied on a marker-string splice. Layers can also now be nested
(``parent_id``) and deleted.

Pure XML, so nothing here needs Inkscape installed.
"""

from __future__ import annotations

import time
from typing import Any

from lxml import etree
from pydantic import BaseModel

from ..security import atomic_output
from ._svg_io import parse_svg, write_tree

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"

_G = f"{{{SVG_NS}}}g"
_GROUPMODE = f"{{{INKSCAPE_NS}}}groupmode"
_LABEL = f"{{{INKSCAPE_NS}}}label"
_INSENSITIVE = f"{{{SODIPODI_NS}}}insensitive"
_NSMAP = {"inkscape": INKSCAPE_NS, "sodipodi": SODIPODI_NS}

OPERATIONS = ("list", "get", "create", "rename", "delete", "show", "hide", "lock", "unlock", "reorder")


class LayerResult(BaseModel):
    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


class _LayerError(Exception):
    """A user-facing problem (bad id, bad position). Not a bug."""


# ---------------------------------------------------------------------------- helpers


def _is_layer(el: etree._Element) -> bool:
    return bool(el.tag == _G and el.get(_GROUPMODE) == "layer")


def _layers(root: etree._Element) -> list[etree._Element]:
    """All layers in document order (sublayers included)."""
    return [el for el in root.iter(_G) if _is_layer(el)]


def _style(el: etree._Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, _, v = part.partition(":")
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def _set_style(el: etree._Element, style: dict[str, str]) -> None:
    if style:
        el.set("style", ";".join(f"{k}:{v}" for k, v in style.items()))
    elif "style" in el.attrib:
        del el.attrib["style"]


def _visible(el: etree._Element) -> bool:
    return _style(el).get("display", "inline") != "none"


def _locked(el: etree._Element) -> bool:
    return bool(el.get(_INSENSITIVE) == "true")


def _depth(el: etree._Element) -> int:
    return sum(1 for a in el.iterancestors(_G) if _is_layer(a))


def _describe(el: etree._Element) -> dict[str, Any]:
    parent = next((a for a in el.iterancestors(_G) if _is_layer(a)), None)
    children = [c for c in el if isinstance(c.tag, str)]
    return {
        "id": el.get("id"),
        "label": el.get(_LABEL),
        "visible": _visible(el),
        "locked": _locked(el),
        "opacity": _style(el).get("opacity"),
        "depth": _depth(el),
        "parent_id": parent.get("id") if parent is not None else None,
        "sublayers": sum(1 for c in children if _is_layer(c)),
        "objects": sum(1 for c in children if not _is_layer(c)),
    }


def _find_layer(root: etree._Element, layer_id: str) -> etree._Element:
    if not layer_id:
        raise _LayerError("layer_id is required")
    for el in _layers(root):
        if el.get("id") == layer_id:
            return el
    raise _LayerError(f"layer {layer_id!r} not found (available: {[el.get('id') for el in _layers(root)]})")


def _unique_id(root: etree._Element, stem: str = "layer") -> str:
    """An id unused by *any* element, not just layers, so ``url(#...)`` references stay unambiguous."""
    taken = {el.get("id") for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
    n = 1
    while f"{stem}{n}" in taken:
        n += 1
    return f"{stem}{n}"


def _next_label(root: etree._Element) -> str:
    used = {el.get(_LABEL) for el in _layers(root)}
    n = len(used) + 1
    while f"Layer {n}" in used:
        n += 1
    return f"Layer {n}"


def _layer_siblings(parent: etree._Element) -> list[etree._Element]:
    return [c for c in parent if _is_layer(c)]


def _place(parent: etree._Element, layer: etree._Element, position: int) -> int:
    """Insert/move ``layer`` so it is the ``position``-th layer among ``parent``'s layers.

    0 is the bottom of the stack (first in document order, painted first); -1 means "on top".
    Returns the final position. Other children (plain objects) keep their relative order.
    """
    siblings = [s for s in _layer_siblings(parent) if s is not layer]
    if position < 0:
        position = len(siblings)
    if position > len(siblings):
        raise _LayerError(f"position {position} out of range (0-{len(siblings)})")
    if layer.getparent() is not None:
        layer.getparent().remove(layer)
    if position == len(siblings):
        # After the last layer if there is one, otherwise at the end of the parent.
        if siblings:
            siblings[-1].addnext(layer)
        else:
            parent.append(layer)
    else:
        siblings[position].addprevious(layer)
    return position


def _root_or_parent(root: etree._Element, parent_id: str) -> etree._Element:
    return _find_layer(root, parent_id) if parent_id else root


# ---------------------------------------------------------------------------- entry point


async def inkscape_layers(
    operation: str,
    input_path: str,
    output_path: str = "",
    layer_id: str = "",
    label: str = "",
    new_label: str = "",
    parent_id: str = "",
    position: int = -1,
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """List and edit the layers of an SVG file (create, rename, delete, show/hide, lock, reorder)."""
    start = time.time()

    def result(ok: bool, message: str, data: dict[str, Any] | None = None, error: str = "") -> dict[str, Any]:
        return LayerResult(
            success=ok,
            operation=operation,
            message=message,
            data=data or {},
            execution_time_ms=(time.time() - start) * 1000,
            error=error,
        ).model_dump()

    if operation not in OPERATIONS:
        return result(False, f"unknown operation {operation!r}; one of {', '.join(OPERATIONS)}", error="ValueError")
    if not input_path:
        return result(False, "input_path required", error="ValueError")

    try:
        tree = parse_svg(input_path)
    except (OSError, etree.XMLSyntaxError) as exc:
        return result(False, f"cannot read SVG: {exc}", error=type(exc).__name__)
    root = tree.getroot()

    try:
        if operation == "list":
            found = [_describe(el) for el in _layers(root)]
            return result(True, f"found {len(found)} layer(s)", {"layers": found, "count": len(found)})

        if operation == "get":
            return result(True, f"layer {layer_id}", {"layer": _describe(_find_layer(root, layer_id))})

        changed: dict[str, Any]
        if operation == "create":
            parent = _root_or_parent(root, parent_id)
            new_id = _unique_id(root)
            layer = etree.Element(_G, nsmap=_NSMAP)
            layer.set("id", new_id)
            layer.set(_GROUPMODE, "layer")
            layer.set(_LABEL, label or _next_label(root))
            placed = _place(parent, layer, position)
            changed = {"id": new_id, "label": layer.get(_LABEL), "position": placed, "parent_id": parent_id or None}
            message = f"created layer {new_id!r} ({layer.get(_LABEL)})"

        else:
            layer = _find_layer(root, layer_id)
            if operation == "rename":
                name = new_label or label
                if not name:
                    raise _LayerError("new_label is required")
                layer.set(_LABEL, name)
                changed, message = {"id": layer_id, "label": name}, f"renamed {layer_id!r} to {name!r}"
            elif operation in ("hide", "show"):
                style = _style(layer)
                style["display"] = "none" if operation == "hide" else "inline"  # what Inkscape writes
                _set_style(layer, style)
                changed = {"id": layer_id, "visible": operation == "show"}
                message = f"{'hid' if operation == 'hide' else 'showed'} layer {layer_id!r}"
            elif operation == "lock":
                layer.set(_INSENSITIVE, "true")
                changed, message = {"id": layer_id, "locked": True}, f"locked layer {layer_id!r}"
            elif operation == "unlock":
                layer.attrib.pop(_INSENSITIVE, None)  # absence is Inkscape's "unlocked"
                changed, message = {"id": layer_id, "locked": False}, f"unlocked layer {layer_id!r}"
            elif operation == "reorder":
                parent = layer.getparent()
                if parent is None:
                    raise _LayerError("cannot reorder the document root")
                placed = _place(parent, layer, position)
                changed, message = {"id": layer_id, "position": placed}, f"moved {layer_id!r} to position {placed}"
            else:  # delete
                removed = sum(1 for _ in layer.iter() if isinstance(_.tag, str))
                layer.getparent().remove(layer)
                changed = {"id": layer_id, "elements_removed": removed}
                message = f"deleted layer {layer_id!r} ({removed} element(s))"

        out = output_path or input_path
        with atomic_output(out) as tmp:
            write_tree(tree, str(tmp))
        return result(True, message, {**changed, "output_path": out})

    except _LayerError as exc:
        return result(False, str(exc), error="ValueError")
    except Exception as exc:
        return result(False, f"layer operation failed: {exc}", error=type(exc).__name__)
