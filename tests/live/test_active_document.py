"""Live ops must say which document they acted on.

`window_id` looked like a router but never routed. Inkscape 1.4 has no focus-window
action, and the bridge plugins are effect extensions that receive whatever desktop is
active — so with two documents open, `inspect_view(window_id=1)` returned window 2's
document, and `set_selection(target=..., window_id=1)` selected an id that existed only
in window 2. With auto-save on, an agent could write to the user's file believing it was
editing its own.

Since it cannot route, `window_id` becomes an assertion instead, and every response
reports the document it actually touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers import payload as _payload

READ_OPS = ["inspect_view", "inspect_layers", "inspect_defs", "get_selection"]


@pytest.mark.parametrize("operation", READ_OPS)
async def test_every_live_op_reports_the_active_document(mcp, live_doc, operation):
    res = await mcp.call_tool("inkscape_live", {"operation": operation})
    p = _payload(res)
    assert p["success"] is True, p

    active = p["data"].get("active_document")
    assert active is not None, f"{operation} must report which document it read"
    assert active.get("docname"), f"active_document needs a docname: {active}"


async def test_active_document_matches_the_file_we_opened(mcp, live_doc):
    res = await mcp.call_tool("inkscape_live", {"operation": "inspect_view"})
    active = _payload(res)["data"]["active_document"]
    assert active["docname"] == "live_doc.svg", f"expected the freshly opened document, got {active}"


async def test_active_document_path_is_never_fabricated(mcp, live_doc):
    """`path` may be empty — Inkscape only tells an extension the *filename*. What it
    must never be is a plausible-looking guess: resolving the docname against the
    extension's CWD produced a confident, wrong absolute path."""
    res = await mcp.call_tool("inkscape_live", {"operation": "inspect_view"})
    active = _payload(res)["data"]["active_document"]
    if active["path"]:
        assert Path(active["path"]).is_absolute()
        assert Path(active["path"]).exists(), f"reported a path that does not exist: {active['path']}"


async def test_window_id_is_refused_when_ambiguous(mcp, live_doc):
    """With several documents open, naming a window cannot be honoured — Inkscape has
    no focus-window action — so the call must refuse instead of silently acting on
    whichever document happens to be active."""
    ping = _payload(await mcp.call_tool("inkscape_live", {"operation": "ping"}))
    windows = ping["data"]["windows"]
    if len(windows) < 2:
        pytest.skip("needs at least two open documents to make window_id ambiguous")

    res = await mcp.call_tool("inkscape_live", {"operation": "inspect_view", "window_id": windows[0]})
    p = _payload(res)

    assert p["success"] is False, "an unhonourable window_id must refuse, not guess"
    assert "active" in p["message"].lower()


async def test_window_id_zero_accepts_the_active_document(mcp, live_doc):
    """The default (0) means "whatever is active" and must always work."""
    res = await mcp.call_tool("inkscape_live", {"operation": "inspect_view", "window_id": 0})
    assert _payload(res)["success"] is True
