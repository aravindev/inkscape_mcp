"""Unknown live operations are rejected before the bridge is touched.

With several documents open, an unknown name used to come back as "ambiguous window"
(the window check ran first), and on Windows/macOS a typo could auto-launch Inkscape.
"""

from __future__ import annotations

from typing import get_args
from unittest.mock import MagicMock

from inkscape_mcp.mcp_tool_types import InkscapeLiveOperation
from inkscape_mcp.tools import live


async def test_unknown_operation_is_rejected_without_the_bridge(monkeypatch):
    get_bus = MagicMock()
    monkeypatch.setattr(live, "_get_bus", get_bus)

    res = await live.inkscape_live(operation="not_a_real_op")

    assert res["success"] is False
    assert res["error"] == "unknown operation"
    get_bus.assert_not_called()


async def test_unknown_operation_wins_over_an_ambiguous_window(monkeypatch):
    bus = MagicMock()
    bus.is_available.return_value = True
    bus.list_windows.return_value = [1, 2]
    monkeypatch.setattr(live, "_get_bus", lambda config=None: bus)

    res = await live.inkscape_live(operation="not_a_real_op", window_id=1)

    assert res["error"] == "unknown operation"


def test_every_advertised_operation_is_dispatched():
    source = open(live.__file__, encoding="utf-8").read()
    for op in get_args(InkscapeLiveOperation):
        assert f'operation == "{op}"' in source, op
