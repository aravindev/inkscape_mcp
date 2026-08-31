"""Four call sites reported "width"/"height" and meant two different things.

`analysis statistics` returned the *page* size; `analysis dimensions`, `file info` and
`vector query_document` shelled out to `--query-width`, which is the *drawing bounding
box*. Same field names, no labels, no way for a caller to tell which it had.

The fixture makes the two unmistakably different: a 400x300 page holding a drawing that
spans only 220x150.
"""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload

PAGE_W, PAGE_H = 400.0, 300.0
DRAW_W, DRAW_H = 220.0, 150.0


def _approx(value, expected):
    return value == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("inkscape_analysis", {"operation": "dimensions"}),
        ("inkscape_file", {"operation": "info"}),
        ("inkscape_vector", {"operation": "query_document"}),
    ],
)
async def test_sites_that_shell_out_report_both(mcp, page_vs_drawing_svg, tool, args):
    """These three already pay for a `--query-*` subprocess, so they report both."""
    res = await mcp.call_tool(tool, {**args, "input_path": str(page_vs_drawing_svg)})
    p = _payload(res)
    assert p["success"] is True, p
    data = p["data"]

    missing = {"page_width", "page_height", "drawing_width", "drawing_height"} - data.keys()
    assert not missing, f"{tool}/{args['operation']} is missing {sorted(missing)}"

    assert _approx(data["page_width"], PAGE_W), data
    assert _approx(data["page_height"], PAGE_H), data
    assert _approx(data["drawing_width"], DRAW_W), data
    assert _approx(data["drawing_height"], DRAW_H), data


async def test_statistics_labels_its_page_size(mcp, page_vs_drawing_svg):
    """`statistics` is deliberately subprocess-free, so it reports the page only —
    but it must NAME it, since that was the whole ambiguity. Reporting a labelled
    subset is honest; reporting an unlabelled number was not."""
    res = await mcp.call_tool(
        "inkscape_analysis",
        {"operation": "statistics", "input_path": str(page_vs_drawing_svg)},
    )
    data = _payload(res)["data"]
    assert _approx(data["page_width"], PAGE_W), data
    assert _approx(data["page_height"], PAGE_H), data
    assert "drawing_width" not in data, "statistics must not pay for a subprocess it doesn't need"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("inkscape_analysis", {"operation": "dimensions"}),
        ("inkscape_file", {"operation": "info"}),
    ],
)
async def test_legacy_width_height_alias_the_page(mcp, page_vs_drawing_svg, tool, args):
    """`width`/`height` stay for one release as deprecated aliases so existing callers
    don't break — but they must now consistently mean the page, not the drawing."""
    res = await mcp.call_tool(tool, {**args, "input_path": str(page_vs_drawing_svg)})
    data = _payload(res)["data"]
    assert _approx(data["width"], PAGE_W), data
    assert _approx(data["height"], PAGE_H), data
