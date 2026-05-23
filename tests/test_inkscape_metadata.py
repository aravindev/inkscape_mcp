"""inkscape_metadata portmanteau — Dublin-Core RDF read/write."""

from __future__ import annotations

from tests._helpers import payload as _payload


async def test_set_title_then_get(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.svg"
    res = await mcp.call_tool(
        "inkscape_metadata",
        {
            "operation": "set_title",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "value": "Hello World",
        },
    )
    assert _payload(res)["success"] is True

    got = await mcp.call_tool(
        "inkscape_metadata",
        {"operation": "get", "input_path": str(out)},
    )
    p = _payload(got)
    assert p["success"] is True
    assert p["data"]["title"] == "Hello World"


async def test_set_creator_then_get(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.svg"
    await mcp.call_tool(
        "inkscape_metadata",
        {
            "operation": "set_creator",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "value": "Test Author",
        },
    )
    got = await mcp.call_tool("inkscape_metadata", {"operation": "get", "input_path": str(out)})
    assert _payload(got)["data"]["creator"] == "Test Author"


async def test_set_description_then_get(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.svg"
    await mcp.call_tool(
        "inkscape_metadata",
        {
            "operation": "set_description",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "value": "A test SVG",
        },
    )
    got = await mcp.call_tool("inkscape_metadata", {"operation": "get", "input_path": str(out)})
    assert _payload(got)["data"]["description"] == "A test SVG"


async def test_set_rights_then_get(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.svg"
    await mcp.call_tool(
        "inkscape_metadata",
        {
            "operation": "set_rights",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "value": "CC-BY 4.0",
        },
    )
    got = await mcp.call_tool("inkscape_metadata", {"operation": "get", "input_path": str(out)})
    assert _payload(got)["data"]["rights"] == "CC-BY 4.0"


async def test_set_keywords_then_get(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.svg"
    res = await mcp.call_tool(
        "inkscape_metadata",
        {
            "operation": "set_keywords",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "value": "a,b,c",
        },
    )
    assert _payload(res)["success"] is True

    got = await mcp.call_tool("inkscape_metadata", {"operation": "get", "input_path": str(out)})
    p = _payload(got)
    assert p["success"] is True
    assert p["data"]["keywords"] == ["a", "b", "c"]
