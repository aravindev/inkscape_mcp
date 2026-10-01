"""Dispatcher guard rails that need no running Inkscape."""

from __future__ import annotations

import inspect
import re

from inkscape_mcp.tools import live


def test_known_operations_match_the_dispatcher():
    """_KNOWN_OPERATIONS is checked before the dispatch chain; a mismatch would either reject a
    real operation or let a dead name through to the 'unknown operation' fallback."""
    handled = set(re.findall(r'operation == "([a-z_]+)"', inspect.getsource(live.inkscape_live)))
    assert handled | {"ping"} == set(live._KNOWN_OPERATIONS)


async def test_unknown_operation_is_rejected_before_touching_the_bus(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("bus must not be created for an unknown operation")

    monkeypatch.setattr(live, "_get_bus", boom)
    res = await live.inkscape_live(operation="definitely_not_an_op")
    assert res["success"] is False
    assert res["error"] == "unknown operation"
