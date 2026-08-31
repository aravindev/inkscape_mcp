"""`ungroup` was a total no-op, and honouring object ids is the whole fix.

Inkscape's bare `select-all` defaults to 'no-groups' — every object *except* groups and
layers. So `select-all; selection-ungroup` had nothing selected that could be ungrouped
and did nothing at all, while reporting success. `select-by-id:<group>` ungroups
correctly, which is why this test lives alongside the scoping work rather than apart
from it.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from tests._helpers import payload as _payload

SVG = "{http://www.w3.org/2000/svg}"


def _ids(path: Path, tag: str) -> set[str]:
    root = etree.parse(str(path)).getroot()
    return {el.get("id") for el in root.iter(f"{SVG}{tag}") if el.get("id")}


async def test_ungroup_removes_the_named_group(mcp, grouped_svg, tmp_path):
    out = tmp_path / "ungrouped.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "ungroup",
            "input_path": str(grouped_svg),
            "output_path": str(out),
            "object_ids": ["grp-1"],
        },
    )
    p = _payload(res)
    assert p["success"] is True, p

    groups = _ids(out, "g")
    assert "grp-1" not in groups, "the requested group must be dissolved"
    assert "grp-2" in groups, "an unrequested group must survive"

    # Children are preserved, just promoted out of the group.
    rects = _ids(out, "rect")
    assert {"g1-a", "g1-b"} <= rects, "ungrouping must not delete the group's children"


async def test_ungroup_reports_failure_when_nothing_to_ungroup(mcp, minimal_svg, tmp_path):
    """minimal.svg has layers but no plain groups — the op cannot do anything, so it
    must say so rather than returning a cheerful success."""
    out = tmp_path / "nothing.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "ungroup",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    p = _payload(res)
    assert p["success"] is False, f"no group to ungroup should not report success: {p}"
