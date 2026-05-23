"""Live-bridge tool tests. Skip cleanly when the Inkscape GUI isn't running."""

from __future__ import annotations

import pytest

from inkscape_mcp.dbus_client import InkscapeDBus
from tests._helpers import payload as _payload


@pytest.fixture(scope="module", autouse=True)
def _bridge_required():
    if not InkscapeDBus().is_available():
        pytest.skip(
            "Inkscape GUI not running — start it to exercise live bridge tests",
            allow_module_level=True,
        )


async def test_ping(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "ping"})
    p = _payload(res)
    assert p["success"] is True
    assert p["data"]["windows"]


async def test_list_actions(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "list_actions"})
    p = _payload(res)
    assert p["success"] is True
    app_names = {a["name"] for a in p["data"]["app"]}
    window_names = {w["name"] for w in p["data"]["window"]}
    assert "select-by-id" in app_names
    assert "paste-in-place" in window_names
    # Annotated form: each entry has a description (may be empty).
    sample = p["data"]["app"][0]
    assert "name" in sample and "description" in sample


async def test_list_actions_filter(mcp):
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "list_actions", "target": "layer-new"},
    )
    p = _payload(res)
    assert p["success"] is True
    # Filter is case-insensitive and matches name or description.
    names = {a["name"] for a in p["data"]["app"]} | {w["name"] for w in p["data"]["window"]}
    assert any("layer-new" in n for n in names)
    # Filter must trim away other actions.
    assert "select-by-id" not in names


async def test_apply_action_select_all(mcp):
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "apply_action", "target": "select-all", "payload": "all"},
    )
    p = _payload(res)
    assert p["success"] is True
    assert p["data"]["scope"] == "app"


async def test_apply_action_unknown(mcp):
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "apply_action", "target": "definitely-not-a-real-action"},
    )
    p = _payload(res)
    assert p["success"] is False
    assert "not registered" in p["message"] or "unknown" in p["error"]


async def test_save_snapshot(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "save_snapshot"})
    p = _payload(res)
    assert p["success"] is True
    assert p["data"]["path"]
    assert p["data"]["bytes"] > 0
    assert "<svg" in p["data"]["xml"]


async def test_get_document_xml(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "get_document_xml"})
    p = _payload(res)
    assert p["success"] is True
    assert "<svg" in p["data"]["xml"]


async def test_get_selection(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "get_selection"})
    p = _payload(res)
    assert p["success"] is True
    assert isinstance(p["data"]["objects"], list)


async def test_set_selection_by_id(mcp):
    # Doesn't matter if the id exists — Inkscape just no-ops if absent. We assert dispatch.
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "set_selection", "target": "rect1"},
    )
    p = _payload(res)
    assert p["success"] is True
    assert p["data"]["action"] == "select-by-id"


async def test_set_selection_by_selector(mcp):
    res = await mcp.call_tool(
        "inkscape_live",
        {"operation": "set_selection", "target": "#rect1"},
    )
    p = _payload(res)
    assert p["success"] is True
    assert p["data"]["action"] == "select-by-selector"


async def test_insert_svg(mcp):
    fragment = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" '
        'viewBox="0 0 40 40"><circle cx="20" cy="20" r="10" fill="#33ff66"/></svg>'
    )
    res = await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": fragment})
    p = _payload(res)
    assert p["success"] is True


async def test_open_file_requires_absolute(mcp):
    res = await mcp.call_tool("inkscape_live", {"operation": "open_file", "target": "relative/path.svg"})
    p = _payload(res)
    assert p["success"] is False
    assert "absolute" in p["message"].lower()


async def test_unknown_operation_dispatch(mcp):
    # Pydantic Literal on the wire rejects unknowns, but the function tolerates them too.
    from inkscape_mcp.tools.live import inkscape_live as live_fn

    p = await live_fn(operation="not_a_real_op")
    assert p["success"] is False
    assert "unknown operation" in p["error"]
