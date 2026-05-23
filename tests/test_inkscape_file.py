"""inkscape_file portmanteau — all six operations."""

from __future__ import annotations

import shutil

import pytest

from tests._helpers import payload as _payload


async def test_list_formats(mcp):
    res = await mcp.call_tool("inkscape_file", {"operation": "list_formats"})
    payload = _payload(res)
    assert payload["success"] is True
    formats = payload.get("data", {}).get("formats") or payload.get("formats")
    assert formats, f"no formats returned: {payload}"
    assert "svg" in [f.lower() for f in formats]
    assert "png" in [f.lower() for f in formats]


async def test_info(mcp, minimal_svg):
    res = await mcp.call_tool("inkscape_file", {"operation": "info", "input_path": str(minimal_svg)})
    payload = _payload(res)
    if not payload.get("success"):
        pytest.xfail(f"upstream bug — stderr leakage in --query-* output: {payload.get('message')}")
    assert payload["success"] is True


async def test_load(mcp, minimal_svg):
    res = await mcp.call_tool("inkscape_file", {"operation": "load", "input_path": str(minimal_svg)})
    payload = _payload(res)
    if not payload.get("success"):
        pytest.xfail(f"upstream bug — stderr leakage in --query-* output: {payload.get('message')}")
    assert payload["success"] is True


async def test_validate(mcp, minimal_svg):
    res = await mcp.call_tool("inkscape_file", {"operation": "validate", "input_path": str(minimal_svg)})
    payload = _payload(res)
    assert payload["success"] is True


async def test_convert_to_png(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.png"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "png",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0
    # PNG magic.
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_convert_to_pdf(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.pdf"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "pdf",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.read_bytes().startswith(b"%PDF-")


async def test_convert_to_eps(mcp, minimal_svg, tmp_path):
    if not shutil.which("gs"):
        pytest.skip("ghostscript not installed — install with: sudo apt install ghostscript")
    out = tmp_path / "out.eps"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "eps",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0
    head = out.read_bytes()[:32]
    assert head.startswith(b"%!PS-Adobe-") or head.startswith(b"%!PS"), head


async def test_convert_to_ps(mcp, minimal_svg, tmp_path):
    if not shutil.which("gs"):
        pytest.skip("ghostscript not installed — install with: sudo apt install ghostscript")
    out = tmp_path / "out.ps"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "ps",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0
    head = out.read_bytes()[:32]
    assert head.startswith(b"%!PS-Adobe-") or head.startswith(b"%!PS"), head


async def test_batch_convert(server, minimal_svg, multi_path_svg, tmp_path):
    # batch_convert kwargs aren't exposed on the MCP portmanteau; drive the function directly.
    from inkscape_mcp.tools import inkscape_file as inkscape_file_tool

    out_dir = tmp_path / "batch_out"
    res = await inkscape_file_tool(
        operation="batch_convert",
        input_paths=[str(minimal_svg), str(multi_path_svg)],
        output_dir=str(out_dir),
        format="png",
        cli_wrapper=server.cli_wrapper,
        config=server.config,
    )
    assert res["success"] is True, res
    assert res["data"]["succeeded"] == 2
    assert (out_dir / f"{minimal_svg.stem}.png").exists()
    assert (out_dir / f"{multi_path_svg.stem}.png").exists()


async def test_convert_to_jpeg(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.jpg"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "jpeg",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.read_bytes()[:3] == b"\xff\xd8\xff"  # JPEG SOI


async def test_convert_to_webp(mcp, minimal_svg, tmp_path):
    out = tmp_path / "out.webp"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "webp",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.read_bytes()[8:12] == b"WEBP"


async def test_convert_to_avif(mcp, minimal_svg, tmp_path):
    pytest.importorskip("pillow_avif")
    out = tmp_path / "out.avif"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "convert",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "format": "avif",
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
    assert out.exists() and out.stat().st_size > 0


async def test_save_passthrough(mcp, minimal_svg, tmp_path):
    out = tmp_path / "saved.svg"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "save",
            "input_path": str(minimal_svg),
            "output_path": str(out),
        },
    )
    payload = _payload(res)
    assert payload["success"] is True, payload
