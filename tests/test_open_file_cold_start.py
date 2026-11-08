"""open_file into a cold managed Inkscape opens one document, not the canvas plus the file.

Launching with the default canvas and then opening the target left two documents, and
with two open every live auto-save refuses ("2 documents are open").
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inkscape_mcp import bus_manager
from inkscape_mcp.tools import live


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "drawing.svg"
    path.write_text("<svg/>", encoding="utf-8")
    return path


def _setup(monkeypatch, *, available: bool, relaunch: bool = True):
    """A managed platform whose bus becomes available once Inkscape is launched."""
    bus = MagicMock()
    state = {"up": available, "pid": 100}
    bus.is_available.side_effect = lambda: state["up"]
    bus.list_windows.return_value = [1]
    launches: list = []

    def auto_launch(config, open_path=None):
        launches.append(open_path)
        state["up"] = True
        if relaunch:
            state["pid"] += 1
        return True

    monkeypatch.setattr(bus_manager, "manages_bus", lambda: True)
    monkeypatch.setattr(bus_manager, "launched_pid", lambda: state["pid"])
    monkeypatch.setattr(live, "_get_bus", lambda config=None: bus)
    monkeypatch.setattr(live, "_auto_launch_inkscape", auto_launch)
    return bus, launches


async def test_cold_open_launches_with_the_file(monkeypatch, doc):
    bus, launches = _setup(monkeypatch, available=False)

    res = await live.inkscape_live(operation="open_file", target=str(doc))

    assert res["success"] is True
    assert res["data"] == {"path": str(doc), "launched": True}
    assert launches == [str(doc)]
    bus.open_file.assert_not_called()


async def test_warm_open_uses_the_bus(monkeypatch, doc):
    bus, launches = _setup(monkeypatch, available=True)

    res = await live.inkscape_live(operation="open_file", target=str(doc))

    assert res["success"] is True
    assert launches == []
    bus.open_file.assert_called_once_with(str(doc))


async def test_cold_open_of_a_missing_file_launches_the_canvas(monkeypatch, tmp_path):
    missing = tmp_path / "missing.svg"
    bus, launches = _setup(monkeypatch, available=False)

    await live.inkscape_live(operation="open_file", target=str(missing))

    assert launches == [None]
    bus.open_file.assert_called_once_with(str(missing))


async def test_other_ops_launch_the_canvas(monkeypatch, doc):
    _, launches = _setup(monkeypatch, available=False)

    await live.inkscape_live(operation="list_actions", target=str(doc))

    assert launches == [None]


async def test_existing_instance_that_registers_late_still_gets_the_open(monkeypatch, doc):
    """ensure_inkscape can return True without launching (a recorded instance registered
    in time); the file was not opened then, so open_file must still send it."""
    bus, launches = _setup(monkeypatch, available=False, relaunch=False)

    res = await live.inkscape_live(operation="open_file", target=str(doc))

    assert launches == [str(doc)]
    assert res["success"] is True
    bus.open_file.assert_called_once_with(str(doc))
