"""Tile-clone helper: duplicate a source element across a grid via <use> refs.

Inkscape's CLI has no tile-clone action, so we synthesise the math ourselves
and write the resulting `<use xlink:href="#id" transform="..."/>` elements
into the document's main layer.
"""

from __future__ import annotations

import time
from typing import Any

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
INK_NS = "http://www.inkscape.org/namespaces/inkscape"
XLINK_NS = "http://www.w3.org/1999/xlink"

SVG = f"{{{SVG_NS}}}"
INK = f"{{{INK_NS}}}"
XLINK = f"{{{XLINK_NS}}}"


def _find_main_layer(root: etree._Element) -> etree._Element:
    """First inkscape:groupmode='layer' group; else the root itself."""
    for g in root.iter(f"{SVG}g"):
        if g.get(f"{INK}groupmode") == "layer":
            return g
    return root


def _ensure_xlink(root: etree._Element) -> None:
    """lxml won't add the xlink namespace declaration unless an element actually uses it.
    We declare it by writing xmlns:xlink on root via nsmap if missing."""
    if "xlink" in (root.nsmap or {}):
        return
    # Rebuild root with xlink in nsmap. lxml requires reconstruction for new namespace prefixes.
    new_nsmap = dict(root.nsmap)
    new_nsmap["xlink"] = XLINK_NS
    new_root = etree.Element(root.tag, attrib=root.attrib, nsmap=new_nsmap)
    for child in root:
        new_root.append(child)
    root.getparent().replace(root, new_root) if root.getparent() is not None else None
    # If no parent, we can't replace; caller handles via tree.getroot() reassign downstream.


def tile_clone(
    input_path: str,
    output_path: str,
    *,
    source_id: str,
    rows: int = 3,
    cols: int = 3,
    x_shift: float = 50,
    y_shift: float = 50,
    rotation_step: float = 0.0,
    scale_step: float = 1.0,
) -> dict[str, Any]:
    """Duplicate <use> references to source_id in a grid.

    Per-cell transform = translate(col*x_shift, row*y_shift)
                       * rotate(index * rotation_step)
                       * scale(scale_step**index)
    Produces rows*cols new <use> elements; the source element itself is unchanged.
    """
    start = time.time()
    try:
        if not input_path:
            return _err("tile_clone", "input_path required", start, "ValueError")
        if not output_path:
            return _err("tile_clone", "output_path required", start, "ValueError")
        if not source_id:
            return _err("tile_clone", "source_id required", start, "ValueError")

        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(input_path, parser)
        root = tree.getroot()

        # Verify the source exists.
        source = None
        for el in root.iter():
            if el.get("id") == source_id:
                source = el
                break
        if source is None:
            return _err("tile_clone", f"source id '{source_id}' not found", start, "NotFound")

        # Declare xlink on root if missing so the serialised output stays valid.
        if "xlink" not in (root.nsmap or {}):
            new_nsmap = dict(root.nsmap)
            new_nsmap["xlink"] = XLINK_NS
            new_root = etree.Element(root.tag, attrib=root.attrib, nsmap=new_nsmap)
            for child in list(root):
                new_root.append(child)
            tree = etree.ElementTree(new_root)
            root = new_root

        layer = _find_main_layer(root)

        created = 0
        index = 0
        for r in range(rows):
            for c in range(cols):
                tx = c * x_shift
                ty = r * y_shift
                rot = index * rotation_step
                scl = scale_step**index
                xform = f"translate({tx:g},{ty:g}) rotate({rot:g}) scale({scl:g})"
                use_el = etree.SubElement(layer, f"{SVG}use")
                use_el.set(f"{XLINK}href", f"#{source_id}")
                use_el.set("transform", xform)
                created += 1
                index += 1

        from ._svg_io import write_tree

        write_tree(tree, output_path)

        return {
            "success": True,
            "operation": "tile_clone",
            "message": f"created {created} clones of #{source_id}",
            "data": {
                "input_path": input_path,
                "output_path": output_path,
                "source_id": source_id,
                "rows": rows,
                "cols": cols,
                "clones_created": created,
            },
            "execution_time_ms": (time.time() - start) * 1000,
            "error": "",
        }
    except Exception as e:
        return _err("tile_clone", f"tile_clone failed: {e}", start, type(e).__name__)


def _err(op: str, msg: str, start: float, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "operation": op,
        "message": msg,
        "data": {},
        "execution_time_ms": (time.time() - start) * 1000,
        "error": error,
    }
