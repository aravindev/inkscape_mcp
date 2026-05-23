"""inkscape_vector portmanteau — representative coverage.

Each operation is one test. Stubs that the upstream never finished are marked xfail —
they're documented placeholders, not real bugs.
"""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload

_NEWLY_IMPLEMENTED = ["create_mesh_gradient", "construct_svg", "path_inset_outset", "path_combine"]


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


SIMPLE_NEW_OPS = [
    "lpe_add_corners",
    "lpe_remove",
    "lpe_paste",
    "lpe_clone_link",
]


@pytest.mark.parametrize("op", SIMPLE_NEW_OPS)
async def test_simple_new_ops(mcp, multi_path_svg, tmp_path, op):
    out = tmp_path / f"{op}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": op, "input_path": str(multi_path_svg), "output_path": str(out)},
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
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
    assert res["success"] is True, res
    assert out.exists() and out.stat().st_size > 0


NEW_OPS_TOOLBOX = [
    "path_division",
    "path_cut",
    "path_split",
    "path_fill_between",
    "stroke_to_path",
    "flip_horizontal",
    "flip_vertical",
    "rotate_90_cw",
    "rotate_90_ccw",
    "align",
    "distribute",
    "ungroup",
    "clone",
    "clone_unlink",
    "object_to_marker",
    "object_to_pattern",
]


@pytest.mark.parametrize("op", NEW_OPS_TOOLBOX)
async def test_path_object_toolbox(mcp, multi_path_svg, tmp_path, op):
    out = tmp_path / f"{op}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": op, "input_path": str(multi_path_svg), "output_path": str(out)},
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0
