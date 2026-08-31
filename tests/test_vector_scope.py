"""Object-scoped operations must act on the objects they were given.

Around fifteen operations hardcoded `select-all` and never consulted `object_id` /
`object_ids`. Asking to convert one circle to a path converted every rect, circle and
text in the document — silently, while naming only the requested object in the response.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from tests._helpers import payload as _payload

SVG = "{http://www.w3.org/2000/svg}"


def _tag_of(path: Path, elem_id: str) -> str | None:
    """Local tag name of the element with `elem_id`, or None if it's gone."""
    for el in etree.parse(str(path)).getroot().iter():
        if el.get("id") == elem_id:
            return etree.QName(el).localname
    return None


async def test_object_to_path_converts_only_the_named_object(mcp, minimal_svg, tmp_path):
    out = tmp_path / "scoped.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "object_to_path",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "object_id": "circle-1",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p

    assert _tag_of(out, "circle-1") == "path", "the requested object should be converted"
    assert _tag_of(out, "rect-1") == "rect", "an unrequested rect must NOT be converted"
    assert _tag_of(out, "text-1") == "text", "an unrequested text must NOT be converted"


async def test_object_to_path_without_ids_still_converts_everything(mcp, minimal_svg, tmp_path):
    """Omitting ids keeps the documented whole-document behaviour."""
    out = tmp_path / "unscoped.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "object_to_path",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    assert _payload(res)["success"] is True
    assert _tag_of(out, "rect-1") == "path"
    assert _tag_of(out, "circle-1") == "path"


def _has_stroke(path: Path, elem_id: str) -> bool:
    """True if the element still paints a stroke. stroke_to_path outlines the stroke
    into a fill and removes it, so this flips only for objects actually operated on."""
    for el in etree.parse(str(path)).getroot().iter():
        if el.get("id") != elem_id:
            continue
        stroke = el.get("stroke") or ""
        style = el.get("style") or ""
        in_style = "stroke:" in style and "stroke:none" not in style
        return bool(in_style or (stroke and stroke != "none"))
    raise AssertionError(f"{elem_id} vanished from {path}")


async def test_stroke_to_path_honours_object_ids(mcp, stroked_svg, tmp_path):
    """A second op on the same code path, to prove the fix is shared rather than
    special-cased for object_to_path. Both paths are stroked identically, so only
    correct scoping can leave exactly one of them alone."""
    out = tmp_path / "stroked_out.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "stroke_to_path",
            "input_path": str(stroked_svg),
            "output_path": str(out),
            "object_ids": ["stroke-a"],
        },
    )
    p = _payload(res)
    assert p["success"] is True, p

    assert not _has_stroke(out, "stroke-a"), "the requested path's stroke should be outlined"
    assert _has_stroke(out, "stroke-b"), "an unrequested path must keep its stroke"
