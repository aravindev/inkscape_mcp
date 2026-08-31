#!/usr/bin/env python3
"""mcp_inspect — unified read-side introspection of the live Inkscape document.

D-Bus actions invoked via the bridge have no return channel, so this
EffectExtension is the canonical way to ask Inkscape questions about the
currently-open document (selection, layers, defs, view state, pages).

Reads ``~/.cache/inkscape_mcp/exchange/input.json``:

    {"category": "selection|layers|defs|view|pages"}

Writes ``~/.cache/inkscape_mcp/exchange/result.json`` with a per-category
response shape. Always carries ``ok`` and ``category`` keys for stable
parsing on the MCP side. The extension never modifies ``self.svg`` — the
inkex framework will emit the document unchanged, producing an
``[unchanged]`` undo-history entry.
"""

import json
import os
import traceback
from pathlib import Path
from typing import Any

import inkex

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

_NS = {
    "svg": "http://www.w3.org/2000/svg",
    "xlink": "http://www.w3.org/1999/xlink",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _write_result(payload: dict) -> None:
    (EXCHANGE_DIR / "result.json").write_text(json.dumps(payload))


def _localname(tag: str) -> str:
    """Strip ``{ns}`` prefix from an etree tag."""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _attr(elem, name: str, default=None):
    """Look up an attribute by either prefixed (``inkscape:label``) or
    Clark (``{...}label``) form. Returns ``default`` if absent."""
    if elem is None:
        return default
    # Try prefixed lookup first via inkex helpers if present.
    if ":" in name:
        prefix, local = name.split(":", 1)
        ns_uri = _NS.get(prefix)
        if ns_uri is not None:
            value = elem.get(f"{{{ns_uri}}}{local}")
            if value is not None:
                return value
            # Some inkex elements accept the prefixed form directly.
            value = elem.get(name)
            if value is not None:
                return value
            return default
    value = elem.get(name)
    return value if value is not None else default


def _parse_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_bool(value, default=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no"):
            return False
    return default


def _namedview(root):
    """Return the first <sodipodi:namedview> element, or None."""
    matches = root.xpath("./sodipodi:namedview", namespaces=_NS)
    if matches:
        return matches[0]
    # Fallback: scan direct children (some older docs structure differently).
    for child in root:
        if _localname(child.tag) == "namedview":
            return child
    return None


def _bbox_dict(elem) -> dict:
    """Return ``{"x","y","w","h"}`` for an element, or ``{}`` if unavailable."""
    try:
        bb = elem.bounding_box()
    except Exception:
        return {}
    if bb is None:
        return {}
    # inkex BoundingBox exposes .left/.top/.width/.height; some versions
    # use .x/.y. Try both.
    try:
        raw_x = getattr(bb, "left", None)
        raw_y = getattr(bb, "top", None)
        if raw_x is None:
            raw_x = getattr(bb, "x", None)
        if raw_y is None:
            raw_y = getattr(bb, "y", None)
        if raw_x is None or raw_y is None:
            return {}
        x = float(raw_x)
        y = float(raw_y)
        w = float(bb.width)
        h = float(bb.height)
    except (TypeError, ValueError, AttributeError):
        return {}
    return {"x": x, "y": y, "w": w, "h": h}


# ---------------------------------------------------------------------------
# Category handlers
# ---------------------------------------------------------------------------


def _inspect_selection(svg, root) -> dict:
    selection = getattr(svg, "selection", None)
    items = []
    if selection is not None:
        # inkex.Selection is iterable; values() works on the dict-like form.
        try:
            iterable = list(selection.values())
        except AttributeError:
            iterable = list(selection)
        items = iterable

    ids = []
    objects = []
    text_pieces: list[str] = []
    for elem in items:
        elem_id = elem.get("id") or ""
        ids.append(elem_id)
        objects.append(
            {
                "id": elem_id,
                "type": _localname(elem.tag),
                "bbox": _bbox_dict(elem),
            }
        )
        # Concatenate any text content inside the element (covers <text>, <tspan>,
        # plus stray text in groups). Replaces the old clipboard-based text grab
        # in tools/live.py::_collect_text.
        for descendant in elem.iter():
            if not isinstance(descendant.tag, str):
                continue
            if descendant.text and descendant.text.strip():
                text_pieces.append(descendant.text.strip())

    return {
        "ok": True,
        "category": "selection",
        "count": len(objects),
        "ids": ids,
        "objects": objects,
        "text": " ".join(text_pieces),
    }


def _inspect_layers(svg, root) -> dict:
    layer_nodes = root.xpath(
        "//svg:g[@inkscape:groupmode='layer']",
        namespaces=_NS,
    )
    namedview = _namedview(root)
    current = _attr(namedview, "inkscape:current-layer")

    layers = []
    for node in layer_nodes:
        # Depth = number of layer ancestors above this one.
        depth = 0
        parent = node.getparent()
        while parent is not None:
            if _localname(parent.tag) == "g" and _attr(parent, "inkscape:groupmode") == "layer":
                depth += 1
            parent = parent.getparent()

        node_id = node.get("id") or ""
        label = _attr(node, "inkscape:label", node_id)

        style = node.get("style", "") or ""
        style_lc = style.lower()
        visible = "display:none" not in style_lc and "visibility:hidden" not in style_lc

        locked = _parse_bool(_attr(node, "sodipodi:insensitive"), False)

        item_count = sum(1 for _ in node)

        layers.append(
            {
                "id": node_id,
                "label": label,
                "visible": visible,
                "locked": bool(locked),
                "depth": depth,
                "item_count": item_count,
            }
        )

    return {
        "ok": True,
        "category": "layers",
        "current": current,
        "layers": layers,
    }


def _inspect_defs(svg, root) -> dict:
    defs_nodes = root.xpath("//svg:defs", namespaces=_NS)

    gradients = []
    filters = []
    markers = []
    patterns = []
    clip_paths = []
    masks = []
    symbols = []

    for defs in defs_nodes:
        for child in defs:
            tag = _localname(child.tag)
            child_id = child.get("id") or ""
            if tag == "linearGradient":
                stops = sum(1 for c in child if _localname(c.tag) == "stop")
                gradients.append({"id": child_id, "type": "linear", "stops": stops})
            elif tag == "radialGradient":
                stops = sum(1 for c in child if _localname(c.tag) == "stop")
                gradients.append({"id": child_id, "type": "radial", "stops": stops})
            elif tag == "filter":
                filters.append(
                    {
                        "id": child_id,
                        "primitive_count": sum(1 for _ in child),
                    }
                )
            elif tag == "marker":
                markers.append({"id": child_id})
            elif tag == "pattern":
                patterns.append({"id": child_id})
            elif tag == "clipPath":
                clip_paths.append({"id": child_id})
            elif tag == "mask":
                masks.append({"id": child_id})
            elif tag == "symbol":
                symbols.append({"id": child_id})

    return {
        "ok": True,
        "category": "defs",
        "gradients": gradients,
        "filters": filters,
        "markers": markers,
        "patterns": patterns,
        "clip_paths": clip_paths,
        "masks": masks,
        "symbols": symbols,
    }


def _inspect_view(svg, root) -> dict:
    namedview = _namedview(root)

    snap_raw = _attr(namedview, "inkscape:snap-global")
    snap_global = _parse_bool(snap_raw, True) if snap_raw is not None else True

    show_grid_raw = _attr(namedview, "showgrid")
    show_grid = _parse_bool(show_grid_raw, None)

    return {
        "ok": True,
        "category": "view",
        "viewbox": root.get("viewBox"),
        "width": root.get("width"),
        "height": root.get("height"),
        "current_layer": _attr(namedview, "inkscape:current-layer"),
        "page_color": _attr(namedview, "pagecolor"),
        "bordercolor": _attr(namedview, "bordercolor"),
        "border_opacity": _parse_float(_attr(namedview, "borderopacity")),
        "zoom": _parse_float(_attr(namedview, "inkscape:zoom")),
        "cx": _parse_float(_attr(namedview, "inkscape:cx")),
        "cy": _parse_float(_attr(namedview, "inkscape:cy")),
        "snap_global": snap_global,
        "show_grid": show_grid,
        "current_page": _attr(namedview, "inkscape:current-page"),
    }


def _inspect_pages(svg, root) -> dict:
    namedview = _namedview(root)
    page_nodes = []
    if namedview is not None:
        page_nodes = namedview.xpath("./inkscape:page", namespaces=_NS)

    pages = []
    for node in page_nodes:
        node_id = node.get("id") or ""
        pages.append(
            {
                "id": node_id,
                "label": _attr(node, "inkscape:label", node_id),
                "x": _parse_float(node.get("x")),
                "y": _parse_float(node.get("y")),
                "width": _parse_float(node.get("width")),
                "height": _parse_float(node.get("height")),
            }
        )

    return {
        "ok": True,
        "category": "pages",
        "count": len(pages),
        "current_id": _attr(namedview, "inkscape:current-page"),
        "pages": pages,
    }


_STYLE_PROPS = (
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-width",
    "stroke-opacity",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "opacity",
    "display",
    "visibility",
    "filter",
    "clip-path",
    "mask",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-anchor",
)


def _document_identity(root) -> dict:
    """Identify the document this extension ran against.

    Reports only what is actually knowable. `sodipodi:docname` is the filename Inkscape
    shows in the title bar; `path` is set ONLY when that is already absolute.

    Resolving a bare docname against the working directory is tempting and wrong: an
    Inkscape extension inherits its CWD from the extension install directory, so that
    produces a confident, plausible, entirely fictional path — which is precisely the
    failure mode this field exists to prevent.
    """
    docname = _attr(root, "sodipodi:docname") or ""
    path = docname if docname.startswith("/") or (len(docname) > 2 and docname[1] == ":") else ""
    return {
        "docname": docname,
        "path": path,
        "root_id": root.get("id") or "",
    }


def _style_declarations(elem) -> dict:
    """Parse the element's inline ``style=""`` into {property: value}.

    Deliberately a plain parse rather than inkex.Style: we need to know which
    properties are *actually declared*, and inkex.Style answers for every property by
    falling back to SVG defaults. Values containing ':' (e.g. ``url(...)``) are
    preserved by splitting on the first colon only.
    """
    raw = elem.get("style") or ""
    out: dict = {}
    for decl in raw.split(";"):
        if ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        name = name.strip()
        value = value.strip()
        if name and value:
            out[name] = value
    return out


def _inspect_element(svg, root, spec) -> dict:
    """Per-element analytical query — geometric + computed style + structure.

    Returns ``bbox`` (post-transform, document coords), ``computed_style``
    (full CSS cascade resolution via inkex.Style — what the renderer
    actually uses), ``attributes`` (raw, including ``inkscape:`` /
    ``sodipodi:`` prefixed forms), and ``ancestors`` (parent chain up to
    the SVG root, with ``is_layer`` markers so the agent can locate the
    containing layer)."""
    target = (spec or {}).get("target", "").strip()
    if not target:
        return {"ok": False, "category": "element", "error": "'target' (element id) is required"}

    elem = svg.getElementById(target) if hasattr(svg, "getElementById") else None
    if elem is None:
        # Fall back to xpath lookup on the root tree.
        matches = root.xpath(f"//*[@id={target!r}]", namespaces=_NS)
        elem = matches[0] if matches else None
    if elem is None:
        return {
            "ok": False,
            "category": "element",
            "error": f"no element with id {target!r}",
        }

    # Computed style, in CSS cascade order.
    #
    # An inline `style=""` declaration outranks the equivalent presentation attribute,
    # so `style` is consulted FIRST — but only for properties that literally appear in
    # the style string. That caveat is the whole reason this used to be the other way
    # round: inkex.Style 1.x reports the SVG *default* for any property it doesn't
    # find, so asking it blindly would let a default (`fill: black`) beat a real
    # presentation attribute (`fill="#cc3333"`).
    #
    # Getting the order wrong is not cosmetic. Anything an Inkscape colour extension
    # touches ends up with both forms — e.g. `fill="#eeaa22" style="fill:#1155dd"` —
    # and the old order reported #eeaa22 while the renderer painted #1155dd.
    computed: dict = {}
    try:
        style = elem.style  # inkex.Style — reads style="..." only
    except Exception:
        style = None

    declared = _style_declarations(elem)

    for prop in _STYLE_PROPS:
        value = None
        # 1. inline style="..." — highest precedence, but only if actually declared.
        if prop in declared:
            value = declared[prop]
        # 2. presentation attribute on the element itself.
        if value is None or value == "":
            value = elem.get(prop)
        # 3. inkex.Style, which fills in inherited values and SVG defaults.
        if (value is None or value == "") and style is not None:
            try:
                value = style(prop) if callable(style) else style.get(prop)
            except Exception:
                value = None
        # Skip empty representations. inkex.Style returns the *Python list*
        # ``[]`` for unset list-valued properties (``stroke-dasharray``,
        # ``filter``), which would stringify to the literal "[]" — not useful.
        # We keep numeric 0 (opacity=0, stroke-width=0 are both meaningful)
        # by only treating empty sequences/strings/None as "no value".
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
            continue
        computed[prop] = str(value)

    # Raw attributes (with prefixed forms for namespaced attrs).
    raw_attrs: dict = {}
    for key, value in elem.attrib.items():
        if isinstance(key, str) and key.startswith("{"):
            # Clark notation → look up prefix.
            uri, local = key[1:].split("}", 1)
            prefix = next((p for p, u in _NS.items() if u == uri), None)
            display_key = f"{prefix}:{local}" if prefix else local
        else:
            display_key = key
        raw_attrs[display_key] = value

    # Ancestor chain — bottom-up, excluding the element itself.
    ancestors: list = []
    node = elem.getparent()
    while node is not None:
        n_id = node.get("id") or ""
        n_label = _attr(node, "inkscape:label") or ""
        groupmode = _attr(node, "inkscape:groupmode")
        ancestors.append(
            {
                "id": n_id,
                "tag": _localname(node.tag),
                "label": n_label,
                "is_layer": groupmode == "layer",
            }
        )
        node = node.getparent()

    return {
        "ok": True,
        "category": "element",
        "id": target,
        "tag": _localname(elem.tag),
        "bbox": _bbox_dict(elem),
        "computed_style": computed,
        "attributes": raw_attrs,
        "ancestors": ancestors,
    }


# Handlers differ in arity (element takes the spec too), so the values are Any.
_DISPATCH: dict[str, Any] = {
    "selection": _inspect_selection,
    "layers": _inspect_layers,
    "defs": _inspect_defs,
    "view": _inspect_view,
    "pages": _inspect_pages,
    "element": _inspect_element,
}


class McpInspect(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = json.loads((EXCHANGE_DIR / "input.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _write_result({"ok": False, "error": f"could not read input.json: {exc}"})
            return

        if not isinstance(spec, dict):
            _write_result({"ok": False, "error": "input.json must decode to an object"})
            return

        category = spec.get("category")
        handler = _DISPATCH.get(category) if isinstance(category, str) else None
        if handler is None:
            _write_result(
                {
                    "ok": False,
                    "category": category,
                    "error": "unknown category",
                }
            )
            return

        # self.svg may be the <svg> root element (modern inkex) or an
        # ElementTree (older). Normalise so handlers always see the root elem.
        root = self.svg.getroot() if hasattr(self.svg, "getroot") else self.svg

        # Element-level queries need extra spec fields (target id); other
        # handlers ignore the third arg.
        if category == "element":
            result = handler(self.svg, root, spec)
        else:
            result = handler(self.svg, root)

        # Which document did this actually run against? Inkscape hands an effect
        # extension the ACTIVE desktop's document, and there is no way to ask for a
        # different one — 1.4 has no focus-window action. So rather than pretend
        # `window_id` routes, every result names the document it touched and the MCP
        # side turns `window_id` into an assertion against it.
        if isinstance(result, dict):
            result["active_document"] = _document_identity(root)
        _write_result(result)


if __name__ == "__main__":
    try:
        McpInspect().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
