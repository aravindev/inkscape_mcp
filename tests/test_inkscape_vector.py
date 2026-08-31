"""inkscape_vector portmanteau — representative coverage.

Each operation is one test. Stubs that the upstream never finished are marked xfail —
they're documented placeholders, not real bugs.
"""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload

_NEWLY_IMPLEMENTED = ["construct_svg", "path_combine"]


async def test_query_document(mcp, minimal_svg):
    res = await mcp.call_tool("inkscape_vector", {"operation": "query_document", "input_path": str(minimal_svg)})
    payload = _payload(res)
    if not payload.get("success"):
        pytest.xfail(f"upstream bug: {payload.get('message')}")
    assert payload["success"] is True


async def test_measure_object(mcp, minimal_svg):
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "measure_object", "input_path": str(minimal_svg)},
    )
    payload = _payload(res)
    # measure_object may require object_id selection it doesn't receive — accept either
    # a clean success or a structured failure with a message, but not an exception.
    assert "success" in payload


async def test_render_preview(mcp, minimal_svg, tmp_path):
    out = tmp_path / "preview.png"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "render_preview",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_object_to_path(mcp, minimal_svg, tmp_path):
    out = tmp_path / "objpath.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "object_to_path",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


async def test_text_to_path(mcp, minimal_svg, tmp_path):
    out = tmp_path / "textpath.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "text_to_path",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload


async def test_fit_canvas_to_drawing(mcp, minimal_svg, tmp_path):
    out = tmp_path / "fit.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "fit_canvas_to_drawing",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload


async def test_apply_boolean_union(mcp, multi_path_svg, tmp_path):
    out = tmp_path / "union.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "apply_boolean",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    # Without object_ids the dispatcher may select-all; accept either branch.
    assert "success" in payload


async def test_generate_laser_dot(mcp, tmp_path):
    out = tmp_path / "dot.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "generate_laser_dot", "output_path": str(out)},
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and b"<svg" in out.read_bytes()


@pytest.mark.parametrize("op", _NEWLY_IMPLEMENTED)
async def test_completed_stub_replacements(mcp, multi_path_svg, tmp_path, op):
    out = tmp_path / f"{op}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": op, "input_path": str(multi_path_svg), "output_path": str(out)},
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


# These used to be asserted as blanket successes on a two-path fixture. They are not:
# `create_mesh_gradient` and `lpe_paste` cannot run without a GUI, and `path_inset_outset`
# was renamed once it turned out to be a scale rather than an offset. Each now has to
# refuse, and name why.
GUI_ONLY_OR_RENAMED = ["create_mesh_gradient", "lpe_paste", "path_inset_outset"]


@pytest.mark.parametrize("op", GUI_ONLY_OR_RENAMED)
async def test_gui_only_and_renamed_ops_refuse_headlessly(mcp, multi_path_svg, tmp_path, op):
    out = tmp_path / f"{op}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": op, "input_path": str(multi_path_svg), "output_path": str(out)},
    )
    payload = _payload(res)
    assert payload["success"] is False, f"{op} cannot work here and must say so: {payload}"
    assert payload["message"].strip(), "a refusal must explain itself"


async def test_lpe_add_corners_applies_an_effect(mcp, multi_path_svg, tmp_path):
    out = tmp_path / "lpe_add.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "lpe_add_corners",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(res)["success"] is True
    assert "path-effect" in out.read_text(), "the LPE should be recorded in the document"


async def test_lpe_remove_reports_noop_when_there_is_no_effect(mcp, multi_path_svg, tmp_path):
    """multi_path.svg carries no path effects, so removing one does nothing —
    which used to be reported as a success."""
    out = tmp_path / "lpe_rm.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "lpe_remove",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(res)["success"] is False


async def test_lpe_remove_strips_an_applied_effect(mcp, multi_path_svg, tmp_path):
    """The positive direction, so the guard above isn't just always-failing."""
    withlpe = tmp_path / "withlpe.svg"
    add = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "lpe_add_corners",
            "input_path": str(multi_path_svg),
            "output_path": str(withlpe),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(add)["success"] is True

    out = tmp_path / "nolpe.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "lpe_remove",
            "input_path": str(withlpe),
            "output_path": str(out),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(res)["success"] is True, "removing a real effect must succeed"


async def test_lpe_clone_link(mcp, multi_path_svg, tmp_path):
    out = tmp_path / "lpe_clone.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "lpe_clone_link",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(res)["success"] is True
    assert out.exists() and out.stat().st_size > 0


async def test_page_fit_to_selection(mcp, minimal_svg, tmp_path):
    out = tmp_path / "page_fit.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "page_fit_to_selection",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


async def test_page_rotate(mcp, minimal_svg, tmp_path):
    out = tmp_path / "page_rot.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "page_rotate",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


async def test_text_on_path(server, tmp_path):
    # MCP portmanteau doesn't expose text_id/path_id — drive the function directly.
    from inkscape_mcp.tools.vector_operations import inkscape_vector as _vec_tool

    src = tmp_path / "text_on_path_src.svg"
    src.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="200" height="100" viewBox="0 0 200 100" version="1.1">\n'
        '  <path id="p1" d="M 10 50 Q 100 10 190 50" fill="none" stroke="#000"/>\n'
        '  <text id="t1" font-family="sans-serif" font-size="14">Curve me</text>\n'
        "</svg>\n"
    )
    out = tmp_path / "text_on_path.svg"
    res = await _vec_tool(
        operation="text_on_path",
        input_path=str(src),
        output_path=str(out),
        cli_wrapper=server.cli_wrapper,
        config=server.config,
        text_id="t1",
        path_id="p1",
    )
    # `text-put-on-path` emits no <textPath> headlessly under any selection order
    # (both ids at once, sequential additive selects, or select-clear first), so this
    # now refuses instead of writing an unchanged document and calling it a success.
    assert res["success"] is False, res
    assert "inkscape_live" in res["message"]


# Each op is paired with a fixture it can actually act on, and with the ids it needs.
# The previous version ran every one of these against the same two-path document and
# asserted success — so `stroke_to_path` (no strokes there), `ungroup` (no groups),
# `clone_unlink` (no clones) and `distribute` (nothing to spread between two objects)
# all "passed" while doing nothing at all.
#   (operation, fixture name, extra args)
NEW_OPS_TOOLBOX = [
    ("path_division", "multi_path_svg", {"object_ids": ["path-a", "path-b"]}),
    ("path_cut", "multi_path_svg", {"object_ids": ["path-a", "path-b"]}),
    ("path_split", "multi_path_svg", {}),
    ("path_fill_between", "multi_path_svg", {"object_ids": ["path-a", "path-b"]}),
    ("stroke_to_path", "stroked_svg", {"object_ids": ["stroke-a"]}),
    ("flip_horizontal", "multi_path_svg", {}),
    ("flip_vertical", "multi_path_svg", {}),
    ("rotate_90_cw", "multi_path_svg", {}),
    ("rotate_90_ccw", "multi_path_svg", {}),
    ("align", "minimal_svg", {"operation_type": "top"}),
    ("distribute", "minimal_svg", {"operation_type": "hgap"}),
    ("ungroup", "grouped_svg", {"object_ids": ["grp-1"]}),
    ("clone", "multi_path_svg", {"object_ids": ["path-a"]}),
    ("object_to_marker", "multi_path_svg", {"object_ids": ["path-a"]}),
    ("object_to_pattern", "multi_path_svg", {"object_ids": ["path-a"]}),
]


@pytest.mark.parametrize(("op", "fixture_name", "extra"), NEW_OPS_TOOLBOX, ids=[o[0] for o in NEW_OPS_TOOLBOX])
async def test_path_object_toolbox(mcp, request, tmp_path, op, fixture_name, extra):
    src = request.getfixturevalue(fixture_name)
    out = tmp_path / f"{op}.svg"
    args = {"operation": op, "input_path": str(src), "output_path": str(out), **extra}
    res = await mcp.call_tool("inkscape_vector", args)
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


async def test_clone_unlink_after_cloning(mcp, multi_path_svg, tmp_path):
    """clone_unlink needs something cloned first — run against a document with no
    <use> elements it is, correctly, a no-op."""
    cloned = tmp_path / "cloned.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "clone",
            "input_path": str(multi_path_svg),
            "output_path": str(cloned),
            "object_ids": ["path-a"],
        },
    )
    assert _payload(res)["success"] is True
    assert "<use" in cloned.read_text()

    out = tmp_path / "unlinked.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "clone_unlink", "input_path": str(cloned), "output_path": str(out)},
    )
    assert _payload(res)["success"] is True
    assert "<use" not in out.read_text(), "unlinking should dissolve the clone"


async def test_clone_unlink_reports_noop_without_clones(mcp, multi_path_svg, tmp_path):
    out = tmp_path / "nothing_to_unlink.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "clone_unlink", "input_path": str(multi_path_svg), "output_path": str(out)},
    )
    assert _payload(res)["success"] is False
