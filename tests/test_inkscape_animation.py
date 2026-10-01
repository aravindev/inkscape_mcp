"""inkscape_animation: SMIL / CSS animation applied to elements of an existing SVG."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from fastmcp.exceptions import ToolError
from lxml import etree

from inkscape_mcp.mcp_tool_types import InkscapeAnimationOperation
from inkscape_mcp.tools.animation import OPERATIONS, PRESETS, inkscape_animation
from tests._helpers import payload as _payload

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"


async def _call(mcp, **kw):
    return _payload(await mcp.call_tool("inkscape_animation", kw))


def _el(path: Path, element_id: str) -> etree._Element:
    root = etree.parse(str(path)).getroot()
    return next(e for e in root.iter() if isinstance(e.tag, str) and e.get("id") == element_id)


def _anims(path: Path, element_id: str) -> list[etree._Element]:
    return [c for c in _el(path, element_id) if isinstance(c.tag, str)]


def _kind(node: etree._Element) -> str:
    return etree.QName(node).localname


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    f = tmp_path / "doc.svg"
    f.write_text(
        f"""<?xml version="1.0"?>
<svg xmlns="{SVG}" xmlns:xlink="{XLINK}" width="400" height="300">
  <circle id="c" cx="100" cy="50" r="20" fill="#3366cc"/>
  <rect id="r" x="10" y="20" width="40" height="60" fill="red" transform="rotate(10)" class="old"/>
  <polygon id="poly" points="0,0 40,0 40,20 0,20"/>
  <path id="p" d="M 0 0 L 100 100"/>
  <text id="t" x="5" y="5">hi</text>
  <g id="g"><rect width="1" height="1"/></g>
</svg>"""
    )
    return f


# --------------------------------------------------------------------------- catalogue


async def test_list_presets(mcp):
    p = await _call(mcp, operation="list_presets")
    assert p["success"] and p["data"]["presets"] == list(PRESETS) and len(PRESETS) == 7


def test_registered_operations_match_the_implementation():
    assert set(get_args(InkscapeAnimationOperation)) == set(OPERATIONS)


async def test_unknown_operation_is_rejected(mcp):
    # The MCP schema (a Literal) rejects it before the tool runs...
    with pytest.raises(ToolError):
        await _call(mcp, operation="levitate")
    # ...and the function itself refuses too, for direct callers.
    p = await inkscape_animation(operation="levitate")
    assert p["success"] is False and "unknown operation" in p["message"]


# --------------------------------------------------------------------------- presets on existing elements


@pytest.mark.parametrize("preset", PRESETS)
async def test_every_preset_applies_to_a_circle_and_is_valid_xml(mcp, doc, preset):
    p = await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name=preset)
    assert p["success"], p
    nodes = _anims(doc, "c")
    assert nodes and all(_kind(n) in ("animate", "animateTransform") for n in nodes)
    # The document the user had is otherwise intact.
    assert _el(doc, "c").get("fill") == "#3366cc" and _el(doc, "r").get("transform") == "rotate(10)"


async def test_fade_in_runs_from_transparent_to_opaque_and_holds(mcp, doc):
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="fade_in", duration=2)
    n = _anims(doc, "c")[0]
    assert (n.get("attributeName"), n.get("from"), n.get("to"), n.get("dur"), n.get("fill")) == (
        "opacity",
        "0",
        "1",
        "2s",
        "freeze",
    )


async def test_rotate_pivots_on_the_elements_own_centre(mcp, doc):
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="rotate")
    n = _anims(doc, "c")[0]
    assert n.get("type") == "rotate" and n.get("from") == "0 100 50" and n.get("to") == "360 100 50"
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="r", preset_name="rotate")
    assert _anims(doc, "r")[0].get("from") == "0 30 50"  # rect: x + w/2, y + h/2
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="poly", preset_name="rotate")
    assert _anims(doc, "poly")[0].get("from") == "0 20 10"


async def test_pulse_really_scales_about_the_centre(mcp, doc):
    """translate(c*(1-s)) then scale(s) must leave the centre fixed for every keyframe."""
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="pulse", amplitude=50)
    kinds = {n.get("type"): n for n in _anims(doc, "c") if _kind(n) == "animateTransform"}
    translate = [tuple(map(float, v.split())) for v in kinds["translate"].get("values").split(";")]
    scale = [float(v) for v in kinds["scale"].get("values").split(";")]
    assert scale == [1.0, 1.5, 1.0] and len(translate) == len(scale)
    for (tx, ty), s in zip(translate, scale, strict=True):
        assert tx + s * 100 == pytest.approx(100) and ty + s * 50 == pytest.approx(
            50
        )  # centre (100, 50) is a fixed point
    assert kinds["translate"].get("additive") == "sum" == kinds["scale"].get("additive")


async def test_pivot_presets_need_a_centre_for_shapes_without_one(mcp, doc):
    for target in ("p", "t", "g"):
        p = await _call(mcp, operation="apply_preset", input_path=str(doc), target_id=target, preset_name="rotate")
        assert p["success"] is False and "cx and cy" in p["message"]
    ok = await _call(
        mcp, operation="apply_preset", input_path=str(doc), target_id="p", preset_name="rotate", cx=50, cy=50
    )
    assert ok["success"] and _anims(doc, "p")[0].get("from") == "0 50 50"


async def test_preset_translate_animations_keep_the_elements_own_transform(mcp, doc):
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="r", preset_name="bounce")
    assert _el(doc, "r").get("transform") == "rotate(10)"
    assert _anims(doc, "r")[0].get("additive") == "sum"  # without it the rotate(10) is replaced


async def test_bad_preset_and_missing_target(mcp, doc):
    assert (await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="warp"))[
        "success"
    ] is False
    p = await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="ghost", preset_name="bounce")
    assert p["success"] is False and "not found" in p["message"]
    assert (await _call(mcp, operation="apply_preset", input_path=str(doc), preset_name="bounce"))["success"] is False


# --------------------------------------------------------------------------- animate_attribute


async def test_animate_attribute_basic(mcp, doc):
    p = await _call(
        mcp, operation="animate_attribute", input_path=str(doc), target_id="c", attribute="r", values="10;30;10",
        duration=2.5, repeat="3",
    )  # fmt: skip
    assert p["success"], p
    n = _anims(doc, "c")[0]
    assert (n.get("attributeName"), n.get("values"), n.get("dur"), n.get("repeatCount")) == (
        "r",
        "10;30;10",
        "2.5s",
        "3",
    )
    assert n.get("calcMode") is None  # linear unless splines are supplied: spline without keySplines is invalid SMIL


async def test_key_splines_come_with_calcmode_and_correct_counts(mcp, doc):
    ok = await _call(
        mcp, operation="animate_attribute", input_path=str(doc), target_id="c", attribute="cx", values="0;50;100",
        key_times="0;0.5;1", key_splines="0.4 0 0.2 1;0.4 0 0.2 1",
    )  # fmt: skip
    assert ok["success"], ok
    n = _anims(doc, "c")[0]
    assert n.get("calcMode") == "spline" and n.get("keySplines") and n.get("keyTimes") == "0;0.5;1"


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        ({"key_times": "0;1"}, "one entry per value"),
        ({"key_splines": "0 0 1 1"}, "needs key_times"),
        ({"key_times": "0;0.5;1", "key_splines": "0 0 1 1"}, "one entry per interval"),
    ],
)
async def test_inconsistent_timing_is_rejected(mcp, doc, extra, needle):
    p = await _call(
        mcp,
        operation="animate_attribute",
        input_path=str(doc),
        target_id="c",
        attribute="cx",
        values="0;50;100",
        **extra,
    )
    assert p["success"] is False and needle in p["message"]


async def test_attribute_and_values_cannot_inject_markup(mcp, doc):
    before = doc.read_bytes()
    attacks = [
        {"attribute": 'x" onload="alert(1)', "values": "1;2"},
        {"attribute": "r", "values": '1;2"/><script>alert(1)</script><x a="'},
        {"attribute": "r", "values": "<b>1</b>;2"},
        {"attribute": "", "values": "1;2"},
        {"attribute": "r", "values": "5"},  # one value is not an animation
    ]
    for a in attacks:
        p = await _call(mcp, operation="animate_attribute", input_path=str(doc), target_id="c", **a)
        assert p["success"] is False, a
    assert doc.read_bytes() == before
    assert b"script" not in before


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
async def test_invalid_durations(doc, duration):
    """Called directly: JSON cannot carry NaN/Infinity, so over MCP those never even arrive."""
    before = doc.read_bytes()
    p = await inkscape_animation(
        operation="apply_preset", input_path=str(doc), target_id="c", preset_name="bounce", duration=duration
    )
    assert p["success"] is False and "duration" in p["message"]
    assert doc.read_bytes() == before


async def test_invalid_repeat_and_fill_mode(mcp, doc):
    base = {
        "operation": "animate_attribute",
        "input_path": str(doc),
        "target_id": "c",
        "attribute": "r",
        "values": "1;2",
    }
    assert (await _call(mcp, **base, repeat="forever"))["success"] is False
    assert (await _call(mcp, **base, fill_mode="bounce"))["success"] is False


# --------------------------------------------------------------------------- animate_transform / motion / color


async def test_animate_transform_keeps_existing_transform(mcp, doc):
    p = await _call(
        mcp, operation="animate_transform", input_path=str(doc), target_id="r", transform_type="scale", values="1;2"
    )
    assert p["success"]
    n = _anims(doc, "r")[0]
    assert _kind(n) == "animateTransform" and n.get("type") == "scale" and n.get("additive") == "sum"
    assert _el(doc, "r").get("transform") == "rotate(10)"
    bad = await _call(
        mcp, operation="animate_transform", input_path=str(doc), target_id="r", transform_type="warp", values="1;2"
    )
    assert bad["success"] is False


async def test_animate_motion_with_path_data_and_with_an_existing_path(mcp, doc):
    ok = await _call(
        mcp, operation="animate_motion", input_path=str(doc), target_id="c", path_data="M 0,0 C 50,0 50,100 100,100",
        rotate_auto=True, duration=3,
    )  # fmt: skip
    assert ok["success"]
    n = _anims(doc, "c")[0]
    assert n.get("path") == "M 0,0 C 50,0 50,100 100,100" and n.get("rotate") == "auto" and n.get("dur") == "3s"
    ok = await _call(mcp, operation="animate_motion", input_path=str(doc), target_id="r", path_id="p")
    assert ok["success"]
    mpath = _anims(doc, "r")[0][0]
    assert _kind(mpath) == "mpath" and mpath.get(f"{{{XLINK}}}href") == "#p"


async def test_animate_motion_rejects_bad_input(mcp, doc):
    base = {"operation": "animate_motion", "input_path": str(doc), "target_id": "c"}
    assert (await _call(mcp, **base))["success"] is False  # neither path_data nor path_id
    assert (await _call(mcp, **base, path_id="ghost"))["success"] is False
    assert (await _call(mcp, **base, path_data='M 0 0"/><script/>'))["success"] is False


async def test_animate_color_defaults_to_current_value(mcp, doc):
    p = await _call(mcp, operation="animate_color", input_path=str(doc), target_id="c", color_to="#ff0000")
    assert p["success"]
    n = _anims(doc, "c")[0]
    assert n.get("attributeName") == "fill" and n.get("values") == "#3366cc;#ff0000;#3366cc"
    assert (await _call(mcp, operation="animate_color", input_path=str(doc), target_id="c"))["success"] is False


# --------------------------------------------------------------------------- css


async def test_css_animation_adds_rule_and_merges_the_class(mcp, doc):
    p = await _call(
        mcp, operation="css_animation", input_path=str(doc), target_id="r", animation_name="fade",
        css_keyframes="from{opacity:0} to{opacity:1}", duration=2,
    )  # fmt: skip
    assert p["success"], p
    root = etree.parse(str(doc)).getroot()
    style = root.find(f"{{{SVG}}}style")
    assert "@keyframes fade" in style.text and ".fade" in style.text and "animation: fade 2s infinite" in style.text
    assert _el(doc, "r").get("class") == "old fade"
    await _call(
        mcp, operation="css_animation", input_path=str(doc), target_id="c", animation_name="grow",
        css_keyframes="to{transform:scale(2)}",
    )  # fmt: skip
    style = etree.parse(str(doc)).getroot().find(f"{{{SVG}}}style")
    assert "@keyframes fade" in style.text and "@keyframes grow" in style.text  # appended, not replaced


@pytest.mark.parametrize(
    ("name", "kf"),
    [
        ("a.b", "to{opacity:1}"),
        ("a b", "to{opacity:1}"),
        ("ok", "</style><script>x</script>"),
        ("ok", "to{background:url(http://evil/x)}"),
        ("ok", "@import 'http://evil/x.css';"),
        ("ok", ""),
        ("", "to{opacity:1}"),
    ],
)
async def test_css_animation_rejects_unsafe_input(mcp, doc, name, kf):
    before = doc.read_bytes()
    p = await _call(
        mcp, operation="css_animation", input_path=str(doc), target_id="c", animation_name=name, css_keyframes=kf
    )
    assert p["success"] is False
    assert doc.read_bytes() == before


# --------------------------------------------------------------------------- list / remove


async def test_list_and_remove_animations(mcp, doc):
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="pulse")  # 3 nodes
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="r", preset_name="bounce")  # 1 node
    allp = await _call(mcp, operation="list_animations", input_path=str(doc))
    assert allp["data"]["count"] == 4
    one = await _call(mcp, operation="list_animations", input_path=str(doc), target_id="c")
    assert one["data"]["count"] == 3 and {a["element"] for a in one["data"]["animations"]} == {"c"}
    rem = await _call(mcp, operation="remove_animation", input_path=str(doc), target_id="c")
    assert rem["success"] and _anims(doc, "c") == []
    assert len(_anims(doc, "r")) == 1  # others untouched
    assert (await _call(mcp, operation="list_animations", input_path=str(doc)))["data"]["count"] == 1


# --------------------------------------------------------------------------- standalone demo / io


async def test_standalone_demo_is_written_and_animated(mcp, tmp_path):
    out = tmp_path / "demo.svg"
    p = await _call(
        mcp, operation="apply_preset", preset_name="bounce", output_path=str(out), x=120, y=80, r=30, fill="#ff8800"
    )
    assert p["success"] and p["data"]["standalone"] is True
    circle = _el(out, "demo")
    assert (circle.get("cx"), circle.get("cy"), circle.get("r"), circle.get("fill")) == ("120", "80", "30", "#ff8800")
    assert _kind(_anims(out, "demo")[0]) == "animateTransform"
    # rotate works standalone too, since the demo circle's centre is known
    out2 = tmp_path / "demo2.svg"
    assert (await _call(mcp, operation="apply_preset", preset_name="rotate", output_path=str(out2), x=50, y=60))[
        "success"
    ]
    assert _anims(out2, "demo")[0].get("from") == "0 50 60"


async def test_standalone_requires_output_and_only_for_presets(mcp, tmp_path):
    assert (await _call(mcp, operation="apply_preset", preset_name="bounce"))["success"] is False
    p = await _call(
        mcp,
        operation="animate_attribute",
        target_id="c",
        attribute="r",
        values="1;2",
        output_path=str(tmp_path / "x.svg"),
    )
    assert p["success"] is False and "input_path" in p["message"]
    huge = await _call(
        mcp, operation="apply_preset", preset_name="bounce", output_path=str(tmp_path / "h.svg"), width=10**9
    )
    assert huge["success"] is False


async def test_output_path_leaves_input_untouched_and_leaves_no_temp_files(mcp, doc, tmp_path):
    before = doc.read_bytes()
    out = tmp_path / "sub" / "o.svg"
    p = await _call(
        mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="shake", output_path=str(out)
    )
    assert p["success"] and doc.read_bytes() == before and _anims(out, "c")
    assert not list(out.parent.glob("*.tmp-*"))


async def test_inkscape_loads_an_animated_file(mcp, doc):
    """Inkscape ignores SMIL/CSS animation but must still open the document."""
    await _call(mcp, operation="apply_preset", input_path=str(doc), target_id="c", preset_name="pulse")
    await _call(
        mcp,
        operation="css_animation",
        input_path=str(doc),
        target_id="r",
        animation_name="fade",
        css_keyframes="to{opacity:0}",
    )
    res = _payload(await mcp.call_tool("inkscape_file", {"operation": "validate", "input_path": str(doc)}))
    assert res["success"] is True, res
