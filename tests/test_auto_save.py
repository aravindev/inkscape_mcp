"""Unit tests for Pattern A auto-save behavior in tools/live.py."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from inkscape_mcp.tools import live


def _bus() -> MagicMock:
    """A bus whose window scope offers document-save, as on Linux."""
    bus = MagicMock()
    bus.list_actions.return_value = ["document-save"]
    return bus


@pytest.fixture(autouse=True)
def _clear_kill_switch(monkeypatch):
    monkeypatch.delenv("INKSCAPE_MCP_AUTO_SAVE", raising=False)


@pytest.mark.parametrize(
    "action,expected",
    [
        ("select-by-id", False),
        ("select-clear", False),
        ("select-all", False),
        ("select-invert", False),
        ("select-by-selector", False),
        ("copy", False),
        ("document-save", False),
        ("document-revert", False),
        ("zoom-in", False),
        ("view-rotate", False),
        ("export-do", False),
        ("list-actions", False),
        ("dialog-clonetiler", False),
        ("object-set-attribute", True),
        ("transform-rotate", True),
        ("path-union", True),
        ("delete-selection", True),
        ("paste-in-place", True),
        ("selection-group", True),
        ("selection-hide", True),
        ("object-to-path", True),
    ],
)
def test_action_mutates_classification(action, expected):
    assert live._action_mutates_document(action) is expected


async def test_save_fires_after_mutating_action():
    bus = _bus()
    saved = await live._activate_with_optional_save(bus, "object-set-attribute", ["fill,#ff0000"])
    assert saved is True
    assert bus.activate.call_count == 2
    bus.activate.assert_any_call("object-set-attribute", ["fill,#ff0000"], scope="app", window_id=1)
    bus.activate.assert_any_call("document-save", scope="window", window_id=1)


async def test_save_does_not_fire_after_read_only_action():
    bus = _bus()
    saved = await live._activate_with_optional_save(bus, "select-clear")
    assert saved is False
    bus.activate.assert_called_once_with("select-clear", None, scope="app", window_id=1)


async def test_kill_switch_disables_save(monkeypatch):
    monkeypatch.setenv("INKSCAPE_MCP_AUTO_SAVE", "0")
    bus = _bus()
    saved = await live._activate_with_optional_save(bus, "object-set-attribute", ["fill,#ff0000"])
    assert saved is False
    bus.activate.assert_called_once_with("object-set-attribute", ["fill,#ff0000"], scope="app", window_id=1)


async def test_save_failure_does_not_propagate():
    bus = _bus()
    bus.activate.side_effect = [None, OSError("save failed")]
    saved = await live._activate_with_optional_save(bus, "transform-rotate", ["45"])
    assert saved is False
    # The original action still fired.
    assert bus.activate.call_args_list[0] == call("transform-rotate", ["45"], scope="app", window_id=1)


async def test_window_scope_respected():
    bus = _bus()
    await live._activate_with_optional_save(bus, "selection-hide", scope="window", window_id=2)
    bus.activate.assert_any_call("selection-hide", None, scope="window", window_id=2)
    bus.activate.assert_any_call("document-save", scope="window", window_id=2)
