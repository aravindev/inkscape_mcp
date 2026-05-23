"""inkscape_gradient portmanteau — XML-mutation gradient ops."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from tests._helpers import payload as _payload

SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"

GRADIENT_SVG = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
  <defs>
    <linearGradient id="grad1" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ff0000" stop-opacity="1"/>
      <stop offset="100%" stop-color="#0000ff" stop-opacity="1"/>
    </linearGradient>
  </defs>
  <rect id="rect-1" x="10" y="10" width="180" height="80" fill="url(#grad1)"/>
</svg>
"""


@pytest.fixture
def gradient_svg(tmp_path: Path) -> Path:
    p = tmp_path / "grad.svg"
    p.write_text(GRADIENT_SVG)
    return p


def _stop_count(path: Path, gid: str) -> int:
    root = etree.parse(str(path)).getroot()
    for tag in ("linearGradient", "radialGradient"):
        for el in root.iter(f"{SVG}{tag}"):
            if el.get("id") == gid:
                return len(list(el.iter(f"{SVG}stop")))
    return -1


async def test_add_stop(mcp, gradient_svg, tmp_path):
    out = tmp_path / "out.svg"
    res = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "add_stop",
            "input_path": str(gradient_svg),
            "output_path": str(out),
            "gradient_id": "grad1",
            "stop_offset": "50%",
            "stop_color": "#00ff00",
            "stop_opacity": 1.0,
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert _stop_count(out, "grad1") == 3


async def test_list_stops_after_add(mcp, gradient_svg, tmp_path):
    out = tmp_path / "out.svg"
    await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "add_stop",
            "input_path": str(gradient_svg),
            "output_path": str(out),
            "gradient_id": "grad1",
            "stop_offset": "50%",
            "stop_color": "#00ff00",
        },
    )
    res = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "list_stops",
            "input_path": str(out),
            "output_path": "",
            "gradient_id": "grad1",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    stops = p["data"]["stops"]
    assert len(stops) == 3


async def test_set_stop_color(mcp, gradient_svg, tmp_path):
    out = tmp_path / "out.svg"
    res = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "set_stop_color",
            "input_path": str(gradient_svg),
            "output_path": str(out),
            "gradient_id": "grad1",
            "stop_offset": "0%",
            "stop_color": "#abcdef",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    # The first stop should now be the new colour.
    root = etree.parse(str(out)).getroot()
    grad = next(el for el in root.iter(f"{SVG}linearGradient") if el.get("id") == "grad1")
    first = next(iter(grad.iter(f"{SVG}stop")))
    style = first.get("style") or ""
    assert "#abcdef" in (first.get("stop-color") or "") or "#abcdef" in style


async def test_remove_stop(mcp, gradient_svg, tmp_path):
    # Start from a 3-stop file so removal leaves 2.
    mid = tmp_path / "mid.svg"
    await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "add_stop",
            "input_path": str(gradient_svg),
            "output_path": str(mid),
            "gradient_id": "grad1",
            "stop_offset": "50%",
            "stop_color": "#00ff00",
        },
    )
    out = tmp_path / "out.svg"
    res = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "remove_stop",
            "input_path": str(mid),
            "output_path": str(out),
            "gradient_id": "grad1",
            "stop_offset": "50%",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert _stop_count(out, "grad1") == 2


async def test_convert_radial_then_linear_roundtrip(mcp, gradient_svg, tmp_path):
    radial = tmp_path / "radial.svg"
    res1 = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "convert_to_radial",
            "input_path": str(gradient_svg),
            "output_path": str(radial),
            "gradient_id": "grad1",
        },
    )
    assert _payload(res1)["success"] is True
    root = etree.parse(str(radial)).getroot()
    assert any(el.get("id") == "grad1" for el in root.iter(f"{SVG}radialGradient")), "should now be radial"

    linear = tmp_path / "linear.svg"
    res2 = await mcp.call_tool(
        "inkscape_gradient",
        {
            "operation": "convert_to_linear",
            "input_path": str(radial),
            "output_path": str(linear),
            "gradient_id": "grad1",
        },
    )
    assert _payload(res2)["success"] is True
    root2 = etree.parse(str(linear)).getroot()
    assert any(el.get("id") == "grad1" for el in root2.iter(f"{SVG}linearGradient")), (
        "should be linear again after round-trip"
    )
