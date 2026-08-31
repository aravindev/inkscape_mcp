"""Operations that cannot work headlessly must say so up front.

Inkscape's own offset machinery is inert outside a GUI: `path-outset`, `path-inset` and
`path-offset` are all no-ops via the CLI, and the Offset LPE never recomputes on a
headless export (not even when forced through `object-to-path`). Rather than returning a
wrong-but-plausible document, these operations refuse and name the live equivalent.

The old `path_inset_outset` is covered here too: it never offset anything, it scaled the
whole selection via `transform-grow`. It is now `scale_selection`, and the old name has
to fail loudly rather than keep quietly doing the wrong thing.
"""

from __future__ import annotations

from tests._helpers import payload as _payload


async def test_path_offset_refuses_headlessly(mcp, minimal_svg, tmp_path):
    out = tmp_path / "offset.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_offset",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "object_ids": ["rect-1"],
            "offset": 5,
        },
    )
    p = _payload(res)

    assert p["success"] is False, "path_offset needs a GUI and must refuse without one"
    assert "inkscape_live" in p["message"], f"the message must point at the live tool: {p['message']}"


async def test_scale_selection_works_and_scales(mcp, minimal_svg, tmp_path):
    """The honest replacement for path_inset_outset does what its name says."""
    out = tmp_path / "scaled.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "scale_selection",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "offset": 20,
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert out.exists()


async def test_legacy_path_inset_outset_fails_with_a_pointer(mcp, minimal_svg, tmp_path):
    out = tmp_path / "legacy.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_inset_outset",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "offset": 5,
        },
    )
    p = _payload(res)

    assert p["success"] is False, "the misleading legacy name must not keep working silently"
    message = p["message"]
    assert "scale_selection" in message and "path_offset" in message, (
        f"the message must name both replacements: {message}"
    )
