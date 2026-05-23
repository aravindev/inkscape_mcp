"""tile_clone helper — pure-Python grid duplication via <use> refs."""

from __future__ import annotations

from lxml import etree

from inkscape_mcp.tools.tile_clone import tile_clone

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
SVG = f"{{{SVG_NS}}}"
XLINK = f"{{{XLINK_NS}}}"


def test_tile_clone_creates_use_grid(minimal_svg, tmp_path):
    out = tmp_path / "tiled.svg"
    res = tile_clone(
        input_path=str(minimal_svg),
        output_path=str(out),
        source_id="rect-1",
        rows=2,
        cols=3,
        x_shift=60,
        y_shift=60,
    )
    assert res["success"] is True, res
    assert out.exists()

    root = etree.parse(str(out)).getroot()
    uses = [u for u in root.iter(f"{SVG}use") if u.get(f"{XLINK}href") == "#rect-1"]
    # rows * cols = 2 * 3 = 6 new <use> refs.
    assert len(uses) == 6


def test_tile_clone_rejects_missing_source(minimal_svg, tmp_path):
    out = tmp_path / "tiled.svg"
    res = tile_clone(
        input_path=str(minimal_svg),
        output_path=str(out),
        source_id="does-not-exist",
        rows=2,
        cols=2,
    )
    assert res["success"] is False
    assert "not found" in res["message"].lower()


def test_tile_clone_applies_rotation_and_scale(minimal_svg, tmp_path):
    out = tmp_path / "tiled.svg"
    res = tile_clone(
        input_path=str(minimal_svg),
        output_path=str(out),
        source_id="rect-1",
        rows=2,
        cols=2,
        rotation_step=10.0,
        scale_step=1.1,
    )
    assert res["success"] is True
    root = etree.parse(str(out)).getroot()
    uses = [u for u in root.iter(f"{SVG}use") if u.get(f"{XLINK}href") == "#rect-1"]
    assert uses, "expected at least one <use>"
    for u in uses:
        t = u.get("transform", "")
        assert "translate(" in t
        assert "rotate(" in t
        assert "scale(" in t
