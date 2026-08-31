"""`insert_svg` must put geometry where the payload says.

The clipboard route (stage to xclip, fire `paste-in-place`) discarded the payload's
coordinates entirely: a rect authored at x=250,y=200 landed at (0,-50) — off the top of
the page and invisible — while the call reported `success: true, saved: true`. Adding a
matching width/height/viewBox to the payload changed nothing.
"""

from __future__ import annotations

from tests._helpers import payload as _payload

FRAGMENT = (
    '<svg xmlns="http://www.w3.org/2000/svg">'
    '<rect id="ins-probe" x="120" y="60" width="40" height="25" fill="#1f2937"/>'
    "</svg>"
)


async def test_inserted_geometry_keeps_its_coordinates(mcp, live_doc):
    ins = await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": FRAGMENT})
    assert _payload(ins)["success"] is True

    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "inspect_element", "target": "ins-probe"},
    )
    p = _payload(res)
    assert p["success"] is True, f"the inserted element should be addressable: {p}"

    bbox = p["data"]["bbox"]
    assert bbox["x"] == 120, f"x must be preserved, got {bbox['x']}"
    assert bbox["y"] == 60, f"y must be preserved, got {bbox['y']}"
    assert bbox["w"] == 40
    assert bbox["h"] == 25


async def test_inserted_element_is_on_page(mcp, live_doc):
    """The regression's visible symptom: negative coordinates put content off-canvas."""
    await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": FRAGMENT})
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "inspect_element", "target": "ins-probe"},
    )
    bbox = _payload(res)["data"]["bbox"]
    assert bbox["x"] >= 0 and bbox["y"] >= 0, f"inserted content landed off-canvas: {bbox}"
