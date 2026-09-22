"""Live D-Bus bridge tests. Skip cleanly when Inkscape GUI isn't running."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from jeepney import HeaderFields

from inkscape_mcp.dbus_client import InkscapeDBus


def test_window_scoped_operations_use_document_object_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = InkscapeDBus()
    paths: list[str] = []

    def send(msg: Any) -> Any:
        paths.append(msg.header.fields[HeaderFields.path])
        if len(paths) == 1:
            return SimpleNamespace(body=[["paste"]])
        return SimpleNamespace(body=["<node><node name='7'/></node>"])

    monkeypatch.setattr(bus, "_send", send)

    assert bus.list_actions(scope="window", window_id=7) == ["paste"]
    assert bus.list_windows() == [7]
    assert paths == [
        "/org/inkscape/Inkscape/document/7",
        "/org/inkscape/Inkscape/document",
    ]


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
    # Window ids are NOT stable: they climb as documents are opened and closed, so a
    # session that has closed its first document has no window 1 at all. Hardcoding it
    # made this fail with "Object does not exist at path .../document/1".
    windows = bus.list_windows()
    if not windows:
        pytest.skip("no Inkscape windows open")
    actions = bus.list_actions(scope="window", window_id=windows[0])
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
    # An Inkscape process with every document closed is a legitimate state — the bus is
    # up and app-scope actions still work, there are just no windows. Asserting >= 1
    # made that report as a failure.
    windows = bus.list_windows()
    assert isinstance(windows, list)
    assert all(isinstance(w, int) for w in windows)
    assert windows == sorted(windows)
