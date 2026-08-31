"""An operation that changes nothing must not report success.

`_simple_action_op` used to return success whenever the Inkscape CLI exited 0 and an
output file appeared — it never compared the document before and after. `path_division`
is the sharpest demonstration: Inkscape's path-division needs exactly two selected
objects, so on any document with more than two it silently does nothing.

The pair of tests below pins both directions: the no-op must be reported as a failure,
and a genuine division must still be reported as a success (no false positives).
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from tests._helpers import payload as _payload

SVG = "{http://www.w3.org/2000/svg}"


def _count(path: Path, tag: str) -> int:
    return sum(1 for _ in etree.parse(str(path)).getroot().iter(f"{SVG}{tag}"))


async def test_path_division_on_crowded_doc_reports_noop(mcp, minimal_svg, tmp_path):
    """minimal.svg holds a rect, a circle and a text — three objects, so division
    cannot run. The document must come back untouched AND be reported as a failure."""
    out = tmp_path / "divided.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_division",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    p = _payload(res)

    assert p["success"] is False, f"a no-op must not report success: {p}"
    assert "no-op" in (p.get("error", "") + p.get("message", "")).lower()


async def test_path_division_on_two_paths_still_succeeds(mcp, multi_path_svg, tmp_path):
    """The guard must not fire when the operation genuinely does something."""
    out = tmp_path / "divided2.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_division",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_ids": ["path-a", "path-b"],
        },
    )
    p = _payload(res)

    assert p["success"] is True, f"a real division must still succeed: {p}"
    assert out.exists()
    # Division splits the lower path where the upper one crosses it.
    assert _count(out, "path") >= 2, "division should leave at least two paths"
