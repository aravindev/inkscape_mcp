"""A managed Inkscape that is alive but never registers on the bus.

Every live call used to wait the registration timeout, then fail with the generic
"bridge not reachable (is the GUI running?)", leaving the user to find the process.
The error now names the PID to quit, and no second instance is launched.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inkscape_mcp import bus_manager
from inkscape_mcp.tools import live


@pytest.fixture
def stuck(monkeypatch, tmp_path):
    exe = tmp_path / "inkscape"
    exe.write_text("")
    launched = MagicMock()
    monkeypatch.setattr(bus_manager, "_inkscape_registered", lambda *a: False)
    monkeypatch.setattr(bus_manager, "_launched_pid", lambda: 4242)
    monkeypatch.setattr(bus_manager, "_pid_alive", lambda pid, exe=None: True)
    monkeypatch.setattr(bus_manager, "_wait_registered", lambda *a: False)
    monkeypatch.setattr(bus_manager.subprocess, "Popen", launched)
    return str(exe), launched


@pytest.mark.parametrize("macos,hint", [(True, "kill 4242"), (False, "taskkill /PID 4242 /F")])
def test_error_names_the_pid(monkeypatch, stuck, macos, hint):
    exe, launched = stuck
    monkeypatch.setattr(bus_manager, "is_macos", lambda: macos)

    with pytest.raises(bus_manager.BusError, match="pid 4242") as err:
        bus_manager.ensure_inkscape("gdbus", "address", exe)

    assert hint in str(err.value)
    launched.assert_not_called()


async def test_live_call_reports_the_pid(monkeypatch, stuck):
    exe, _ = stuck
    bus = MagicMock()
    bus.is_available.return_value = False
    monkeypatch.setattr(bus_manager, "manages_bus", lambda: True)
    monkeypatch.setattr(bus_manager, "find_gdbus", lambda *a: "gdbus")
    monkeypatch.setattr(bus_manager, "ensure_bus", lambda *a: "address")
    monkeypatch.setattr(live, "_get_bus", lambda config=None: bus)
    monkeypatch.setattr(live, "_resolve_inkscape_exe", lambda config: exe)

    res = await live.inkscape_live(operation="get_selection")

    assert res["success"] is False
    assert "pid 4242" in res["message"]
    assert res["message"].startswith("auto-launch of Inkscape failed")
