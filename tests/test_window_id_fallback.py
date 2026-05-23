"""Tests for the multi-window auto-detect helper (`_resolve_window_id`).

Covers the cases that bit us in the live session — window 1 closed, user
opens a new doc as window 4, hardcoded `window_id=1` ops failing with
``Object does not exist at path /org/inkscape/Inkscape/window/1``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inkscape_mcp.tools import live


def _bus(windows):
    bus = MagicMock()
    bus.list_windows.return_value = list(windows)
    return bus


def test_resolve_returns_requested_when_present():
    bus = _bus([1, 2, 3])
    assert live._resolve_window_id(bus, 1) == 1
    assert live._resolve_window_id(bus, 2) == 2
    assert live._resolve_window_id(bus, 3) == 3


def test_resolve_falls_back_to_first_window_when_requested_missing():
    """Bites when user closed window 1 and reopened a doc as window 4."""
    bus = _bus([4])
    assert live._resolve_window_id(bus, 1) == 4


def test_resolve_falls_back_when_default_id_not_in_list():
    bus = _bus([2, 3])  # window 1 closed; user is in 2 and 3
    assert live._resolve_window_id(bus, 1) == 2


def test_resolve_raises_when_no_windows():
    bus = _bus([])
    with pytest.raises(RuntimeError, match="no Inkscape windows"):
        live._resolve_window_id(bus, 1)


def test_resolve_returns_requested_unchanged_when_list_windows_throws():
    """Best-effort: if we can't enumerate windows for any reason, just pass
    the requested id through rather than failing the whole call."""
    bus = MagicMock()
    bus.list_windows.side_effect = RuntimeError("D-Bus hiccup")
    assert live._resolve_window_id(bus, 1) == 1
    assert live._resolve_window_id(bus, 7) == 7
