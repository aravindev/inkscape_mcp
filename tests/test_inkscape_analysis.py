"""inkscape_analysis portmanteau — read-only inspection."""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload


@pytest.mark.parametrize("op", ["quality", "statistics", "validate", "objects", "dimensions", "structure"])
async def test_analysis_operation_succeeds(mcp, minimal_svg, op):
    res = await mcp.call_tool("inkscape_analysis", {"operation": op, "input_path": str(minimal_svg)})
    payload = _payload(res)
    assert payload["success"] is True, f"{op} failed: {payload}"


async def test_dimensions_returns_numbers(mcp, minimal_svg):
    res = await mcp.call_tool("inkscape_analysis", {"operation": "dimensions", "input_path": str(minimal_svg)})
    payload = _payload(res)
    data = payload.get("data") or payload
    # Inkscape reports in user units (1.4.4 default px-equivalent), which is some
    # constant multiple of the fixture's declared 200x100. Just assert real numbers
    # with a 2:1 aspect ratio (matching the fixture's viewBox).
    assert isinstance(data.get("width"), (int, float)) and data["width"] > 0
    assert isinstance(data.get("height"), (int, float)) and data["height"] > 0
    assert abs((data["width"] / data["height"]) - 2.0) < 0.4, data
