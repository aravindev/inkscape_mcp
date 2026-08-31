"""`computed_style` must report what the renderer actually paints.

`mcp_inspect` checked the presentation attribute first and only fell back to the `style`
string. CSS precedence is the reverse, so an element carrying both — as anything touched
by an Inkscape colour extension does — reported the losing declaration. Observed live:
`fill="#eeaa22" style="fill:#1155dd"` reported `#eeaa22`, while the rendered pixel was
`#1155dd`.

The original ordering existed for a real reason (inkex.Style reports SVG *defaults* for
properties set via presentation attributes, and a default must never win over a real
value), so the fallback chain is pinned here too.
"""

from __future__ import annotations

from tests._helpers import payload as _payload


async def _computed_fill(mcp, elem_id: str) -> str:
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "inspect_element", "target": elem_id},
    )
    p = _payload(res)
    assert p["success"] is True, p
    return p["data"]["computed_style"]["fill"]


async def test_style_attribute_beats_presentation_attribute(mcp, live_doc):
    await mcp.call_tool(
        "inkscape_live",
        {
            "operation": "edit_xml",
            "target": '//svg:rect[@id="rect-1"]',
            "payload": '{"action":"set_attr","name":"style","value":"fill:#1155dd"}',
        },
    )
    # rect-1 still carries fill="#cc3333" as a presentation attribute.
    assert await _computed_fill(mcp, "rect-1") == "#1155dd"


async def test_presentation_attribute_used_when_no_style(mcp, live_doc):
    """The fallback the original ordering was protecting must keep working:
    a presentation attribute must beat the SVG default."""
    assert await _computed_fill(mcp, "circle-1") == "#3366cc"
