"""A real offset changes the outline; a scale does not.

`path_inset_outset` claimed to grow or shrink a path outline but fired `transform-grow`,
which uniformly *scales* the selection so its bounding box grows by N. The two are easy
to confuse, and a square cannot tell them apart: offsetting a square with a miter join
produces a (bigger) square, exactly as scaling does.

A non-square rectangle separates them cleanly:

    offset by d  ->  width +2d AND height +2d   (the same absolute amount on both axes)
    scale        ->  width and height grow in PROPORTION to their original sizes

Only reachable with a GUI — `path-outset`, `path-inset` and `path-offset` are all inert
via the CLI, and the Offset LPE never recomputes on a headless export.
"""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload

# 140 x 30 — deliberately far from square, so absolute and proportional growth diverge.
RECT = (
    '<svg xmlns="http://www.w3.org/2000/svg">'
    '<path id="off-rect" d="M 20,100 L 160,100 L 160,130 L 20,130 Z" fill="#3366cc"/>'
    "</svg>"
)


async def _bbox(mcp, elem_id):
    res = await mcp.call_tool("inkscape_live", {"operation": "inspect_element", "target": elem_id})
    p = _payload(res)
    assert p["success"] is True, p
    return p["data"]["bbox"]


async def test_offset_grows_the_outline(mcp, live_doc):
    await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": RECT})
    before = await _bbox(mcp, "off-rect")

    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "path_offset", "target": "off-rect", "payload": '{"offset": 10}'},
    )
    assert _payload(res)["success"] is True, _payload(res)

    after = await _bbox(mcp, "off-rect")
    assert after["w"] > before["w"], "an outward offset must widen the shape"
    assert after["h"] > before["h"]


async def test_offset_is_absolute_not_proportional(mcp, live_doc):
    """The discriminator: both axes must grow by the SAME absolute amount.

    On a 140x30 rect a scale that widened it by 5 would only heighten it by ~1.07
    (30/140 of the width change), so equal deltas can only come from a real offset.
    """
    await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": RECT})
    before = await _bbox(mcp, "off-rect")

    await mcp.call_tool(
        "inkscape_live",
        {"operation": "path_offset", "target": "off-rect", "payload": '{"offset": 10}'},
    )
    after = await _bbox(mcp, "off-rect")

    dw = after["w"] - before["w"]
    dh = after["h"] - before["h"]
    assert dw > 0, "offset produced no change"
    assert dh == pytest.approx(dw, abs=0.01), (
        f"width grew {dw:.3f} but height grew {dh:.3f} — that is a scale, not an offset"
    )


async def test_negative_offset_shrinks(mcp, live_doc):
    await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": RECT})
    before = await _bbox(mcp, "off-rect")

    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "path_offset", "target": "off-rect", "payload": '{"offset": -5}'},
    )
    assert _payload(res)["success"] is True

    after = await _bbox(mcp, "off-rect")
    assert after["w"] < before["w"], "an inward offset must narrow the shape"


async def test_offset_rejects_bad_input(mcp, live_doc):
    for payload, why in (('{"offset": 0}', "zero offset"), ("{}", "missing offset")):
        res = await mcp.call_tool(
            "inkscape_live",
            {"operation": "path_offset", "target": "off-rect", "payload": payload},
        )
        assert _payload(res)["success"] is False, why

    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "path_offset", "target": "rect-1", "payload": '{"offset": 5}'},
    )
    p = _payload(res)
    assert p["success"] is False, "offset applies to paths; a <rect> must be refused"
    assert "path" in p["message"].lower()
