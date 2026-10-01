"""inkscape_layers: layer management on a real XML tree."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from tests._helpers import payload as _payload

INK = "http://www.inkscape.org/namespaces/inkscape"
SOD = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
SVG = "http://www.w3.org/2000/svg"

NESTED = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="{SVG}" xmlns:inkscape="{INK}" xmlns:sodipodi="{SOD}" width="100" height="100">
  <g inkscape:groupmode="layer" id="outer" inkscape:label="Outer">
    <g id="plain-group"><rect id="deep-rect" width="5" height="5"/></g>
    <g inkscape:groupmode="layer" id="inner" inkscape:label="Inner">
      <circle id="inner-circle" r="3"/>
    </g>
    <rect id="outer-rect" width="9" height="9"/>
  </g>
  <g inkscape:groupmode="layer" id="top" inkscape:label="Top" style="opacity:0.5;display:inline"/>
</svg>
"""


@pytest.fixture
def nested_svg(tmp_path: Path) -> Path:
    p = tmp_path / "nested.svg"
    p.write_text(NESTED)
    return p


async def _call(mcp, **kw):
    return _payload(await mcp.call_tool("inkscape_layers", kw))


def _layers(path: Path) -> dict[str, etree._Element]:
    root = etree.parse(str(path)).getroot()
    return {g.get("id"): g for g in root.iter(f"{{{SVG}}}g") if g.get(f"{{{INK}}}groupmode") == "layer"}


def _order(path: Path, parent_id: str | None = None) -> list[str]:
    root = etree.parse(str(path)).getroot()
    parent = root if parent_id is None else _layers(path)[parent_id]
    return [g.get("id") for g in parent if g.get(f"{{{INK}}}groupmode") == "layer"]


# --------------------------------------------------------------------------- list / get


async def test_list_reports_nesting_depth_and_counts(mcp, nested_svg):
    """A layer holding groups and a sublayer broke the regex version (non-greedy </g>)."""
    p = await _call(mcp, operation="list", input_path=str(nested_svg))
    assert p["success"] is True
    by_id = {layer["id"]: layer for layer in p["data"]["layers"]}
    assert set(by_id) == {"outer", "inner", "top"}  # the plain <g> is not a layer
    assert by_id["inner"]["depth"] == 1 and by_id["inner"]["parent_id"] == "outer"
    assert by_id["outer"]["depth"] == 0 and by_id["outer"]["parent_id"] is None
    assert by_id["outer"]["sublayers"] == 1
    assert by_id["outer"]["objects"] == 2  # plain-group + outer-rect
    assert by_id["inner"]["objects"] == 1
    assert by_id["top"]["opacity"] == "0.5"


async def test_get_one_layer_and_unknown_id(mcp, nested_svg):
    ok = await _call(mcp, operation="get", input_path=str(nested_svg), layer_id="inner")
    assert ok["success"] and ok["data"]["layer"]["label"] == "Inner"
    bad = await _call(mcp, operation="get", input_path=str(nested_svg), layer_id="nope")
    assert bad["success"] is False and "not found" in bad["message"] and "outer" in bad["message"]


async def test_list_on_the_shared_fixture(mcp, minimal_svg):
    p = await _call(mcp, operation="list", input_path=str(minimal_svg))
    assert [layer["label"] for layer in p["data"]["layers"]] == ["base", "label"]


# --------------------------------------------------------------------------- create


async def test_create_default_goes_on_top_with_unique_id_and_label(mcp, minimal_svg):
    p = await _call(mcp, operation="create", input_path=str(minimal_svg))
    assert p["success"] and p["data"]["label"] == "Layer 3"
    assert _order(minimal_svg)[-1] == p["data"]["id"]


async def test_created_id_avoids_ids_used_by_non_layers(mcp, tmp_path):
    """layer1 taken by a <rect>: a layers-only uniqueness check would reuse it."""
    f = tmp_path / "a.svg"
    f.write_text(f'<svg xmlns="{SVG}"><rect id="layer1" width="1" height="1"/></svg>')
    p = await _call(mcp, operation="create", input_path=str(f))
    assert p["data"]["id"] == "layer2"


async def test_create_at_bottom_and_as_sublayer(mcp, nested_svg):
    bottom = await _call(mcp, operation="create", input_path=str(nested_svg), label="Bg", position=0)
    assert _order(nested_svg)[0] == bottom["data"]["id"]
    sub = await _call(mcp, operation="create", input_path=str(nested_svg), label="Sub", parent_id="outer")
    assert sub["data"]["parent_id"] == "outer"
    assert _order(nested_svg, "outer")[-1] == sub["data"]["id"]
    assert (await _call(mcp, operation="create", input_path=str(nested_svg), parent_id="ghost"))["success"] is False


async def test_create_position_out_of_range(mcp, minimal_svg):
    p = await _call(mcp, operation="create", input_path=str(minimal_svg), position=99)
    assert p["success"] is False and "out of range" in p["message"]


# --------------------------------------------------------------------------- rename / escaping


@pytest.mark.parametrize("name", ['say "hi"', "a & b", "<script>x</script>", 'it\'s "both"'])
async def test_labels_with_markup_characters_stay_valid_xml(mcp, minimal_svg, name):
    """The regex version wrote the label into the tag unescaped, so a quote corrupted the file."""
    p = await _call(mcp, operation="rename", input_path=str(minimal_svg), layer_id="layer-base", new_label=name)
    assert p["success"], p
    assert _layers(minimal_svg)["layer-base"].get(f"{{{INK}}}label") == name  # parses, and round-trips


async def test_rename_needs_a_label(mcp, minimal_svg):
    p = await _call(mcp, operation="rename", input_path=str(minimal_svg), layer_id="layer-base")
    assert p["success"] is False and "new_label" in p["message"]


# --------------------------------------------------------------------------- show / hide / lock


async def test_hide_and_show_preserve_other_style_properties(mcp, nested_svg):
    await _call(mcp, operation="hide", input_path=str(nested_svg), layer_id="top")
    style = _layers(nested_svg)["top"].get("style")
    assert "display:none" in style and "opacity:0.5" in style
    listed = await _call(mcp, operation="get", input_path=str(nested_svg), layer_id="top")
    assert listed["data"]["layer"]["visible"] is False
    await _call(mcp, operation="show", input_path=str(nested_svg), layer_id="top")
    style = _layers(nested_svg)["top"].get("style")
    assert "display:inline" in style and "display:none" not in style and "opacity:0.5" in style


async def test_hide_is_idempotent(mcp, minimal_svg):
    for _ in range(2):
        await _call(mcp, operation="hide", input_path=str(minimal_svg), layer_id="layer-base")
    assert _layers(minimal_svg)["layer-base"].get("style").count("display:none") == 1


async def test_lock_then_unlock_removes_the_attribute(mcp, minimal_svg):
    await _call(mcp, operation="lock", input_path=str(minimal_svg), layer_id="layer-base")
    assert _layers(minimal_svg)["layer-base"].get(f"{{{SOD}}}insensitive") == "true"
    got = await _call(mcp, operation="get", input_path=str(minimal_svg), layer_id="layer-base")
    assert got["data"]["layer"]["locked"] is True
    await _call(mcp, operation="unlock", input_path=str(minimal_svg), layer_id="layer-base")
    assert f"{{{SOD}}}insensitive" not in _layers(minimal_svg)["layer-base"].attrib  # Inkscape's own "unlocked"


# --------------------------------------------------------------------------- reorder


async def test_reorder_moves_among_sibling_layers_and_keeps_objects(mcp, nested_svg):
    before_objects = [c.get("id") for c in _layers(nested_svg)["outer"] if c.get(f"{{{INK}}}groupmode") != "layer"]
    p = await _call(mcp, operation="reorder", input_path=str(nested_svg), layer_id="top", position=0)
    assert p["success"] and _order(nested_svg) == ["top", "outer"]
    p = await _call(mcp, operation="reorder", input_path=str(nested_svg), layer_id="top", position=-1)
    assert _order(nested_svg) == ["outer", "top"]
    after_objects = [c.get("id") for c in _layers(nested_svg)["outer"] if c.get(f"{{{INK}}}groupmode") != "layer"]
    assert after_objects == before_objects


async def test_reorder_within_a_parent_and_bad_position(mcp, nested_svg):
    await _call(mcp, operation="create", input_path=str(nested_svg), label="Second", parent_id="outer")
    kids = _order(nested_svg, "outer")
    assert len(kids) == 2
    await _call(mcp, operation="reorder", input_path=str(nested_svg), layer_id=kids[1], position=0)
    assert _order(nested_svg, "outer") == [kids[1], kids[0]]
    bad = await _call(mcp, operation="reorder", input_path=str(nested_svg), layer_id="top", position=50)
    assert bad["success"] is False and "out of range" in bad["message"]


# --------------------------------------------------------------------------- delete


async def test_delete_removes_layer_with_contents(mcp, nested_svg):
    p = await _call(mcp, operation="delete", input_path=str(nested_svg), layer_id="outer")
    assert p["success"] and p["data"]["elements_removed"] == 6  # outer, plain-group, deep-rect, inner, circle, rect
    root = etree.parse(str(nested_svg)).getroot()
    ids = {e.get("id") for e in root.iter() if isinstance(e.tag, str)}
    assert not ids & {"outer", "inner", "deep-rect", "inner-circle", "outer-rect"} and "top" in ids


async def test_failed_operation_does_not_touch_the_file(mcp, minimal_svg):
    before = minimal_svg.read_bytes()
    p = await _call(mcp, operation="delete", input_path=str(minimal_svg), layer_id="ghost")
    assert p["success"] is False
    assert minimal_svg.read_bytes() == before


# --------------------------------------------------------------------------- io


async def test_output_path_leaves_the_input_untouched(mcp, minimal_svg, tmp_path):
    before = minimal_svg.read_bytes()
    out = tmp_path / "out" / "copy.svg"
    p = await _call(mcp, operation="hide", input_path=str(minimal_svg), layer_id="layer-base", output_path=str(out))
    assert p["success"] and minimal_svg.read_bytes() == before
    assert "display:none" in _layers(out)["layer-base"].get("style")
    assert not list(out.parent.glob("*.tmp-*"))


async def test_missing_and_malformed_input(mcp, tmp_path):
    p = await _call(mcp, operation="list", input_path=str(tmp_path / "nope.svg"))
    assert p["success"] is False and "cannot read" in p["message"]
    bad = tmp_path / "bad.svg"
    bad.write_text("<svg><g")
    assert (await _call(mcp, operation="list", input_path=str(bad)))["success"] is False
    assert (await _call(mcp, operation="list", input_path=""))["success"] is False


async def test_external_entities_are_not_resolved(mcp, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET-VALUE")
    f = tmp_path / "xxe.svg"
    f.write_text(
        f'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file://{secret}">]>'
        f'<svg xmlns="{SVG}" xmlns:inkscape="{INK}"><g inkscape:groupmode="layer" id="l" inkscape:label="&x;"/></svg>'
    )
    p = await _call(mcp, operation="list", input_path=str(f))
    assert "TOPSECRET-VALUE" not in str(p)


async def test_inkscape_accepts_the_edited_file(mcp, nested_svg):
    """The edits must stay loadable by the real application, not just by lxml."""
    await _call(mcp, operation="create", input_path=str(nested_svg), label='Q"1', parent_id="outer")
    await _call(mcp, operation="hide", input_path=str(nested_svg), layer_id="inner")
    await _call(mcp, operation="reorder", input_path=str(nested_svg), layer_id="top", position=0)
    res = _payload(await mcp.call_tool("inkscape_file", {"operation": "validate", "input_path": str(nested_svg)}))
    assert res["success"] is True, res


async def test_registered_operations_match_the_implementation():
    from typing import get_args

    from inkscape_mcp.mcp_tool_types import InkscapeLayersOperation
    from inkscape_mcp.tools.layers import OPERATIONS

    assert set(get_args(InkscapeLayersOperation)) == set(OPERATIONS)
