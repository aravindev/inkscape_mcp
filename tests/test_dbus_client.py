"""Live D-Bus bridge tests. Skip cleanly when Inkscape GUI isn't running."""

from __future__ import annotations

import pytest

from inkscape_mcp.dbus_client import InkscapeDBus


@pytest.fixture(scope="module")
def bus() -> InkscapeDBus:
    b = InkscapeDBus()
    if not b.is_available():
        pytest.skip("Inkscape GUI not running — start it to exercise the live bridge")
    return b


def test_is_available(bus: InkscapeDBus) -> None:
    assert bus.is_available()


def test_list_actions_app(bus: InkscapeDBus) -> None:
    actions = bus.list_actions(scope="app")
    assert "select-by-id" in actions
    assert len(actions) > 100


def test_list_actions_window(bus: InkscapeDBus) -> None:
    actions = bus.list_actions(scope="window", window_id=1)
    assert "paste" in actions or "paste-in-place" in actions


def test_describe_select_by_id(bus: InkscapeDBus) -> None:
    enabled, sig, defaults = bus.describe("select-by-id")
    assert sig == "s"
    assert isinstance(enabled, bool)
    assert isinstance(defaults, list)


def test_activate_select_all(bus: InkscapeDBus) -> None:
    # select-all takes a string scope parameter ("all", "all-in-all-layers", etc.).
    bus.activate("select-all", ["all"], scope="app")


def test_list_windows(bus: InkscapeDBus) -> None:
    windows = bus.list_windows()
    assert len(windows) >= 1
    assert all(isinstance(w, int) for w in windows)
