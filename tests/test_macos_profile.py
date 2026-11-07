"""Managed macOS preferences must not touch a normal Inkscape profile."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lxml import etree as ET

from inkscape_mcp import bus_manager, extension_bridge, platform_support


@pytest.fixture
def macos_home(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_support, "is_macos", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("INKSCAPE_MCP_SET_PYTHON_PREF", raising=False)
    monkeypatch.delenv("INKSCAPE_PROFILE_DIR", raising=False)
    return tmp_path


def test_interpreter_is_written_only_to_managed_profile(macos_home, monkeypatch):
    normal = macos_home / "normal-profile"
    normal.mkdir()
    prefs = normal / "preferences.xml"
    original = '<inkscape><group id="extensions" python-interpreter="custom-python"/></inkscape>'
    prefs.write_text(original)
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", str(normal))

    result = platform_support.set_inkscape_python_preference("/mcp/bin/python")

    assert result["changed"]
    assert prefs.read_text() == original
    assert platform_support.profile_dir() == normal
    managed = platform_support.live_profile_dir()
    assert managed != normal
    root = ET.parse(managed / "preferences.xml").getroot()
    assert root.find("group").get("python-interpreter") == "/mcp/bin/python"
    assert extension_bridge._user_extensions_dir() == managed / "extensions" / "inkscape_mcp"
    assert not (macos_home / ".cache/inkscape_mcp/inkscape-python-pref.json").exists()


def test_interpreter_refresh_preserves_other_managed_preferences(macos_home):
    platform_support.set_inkscape_python_preference("/old/python")
    prefs = platform_support.live_profile_dir() / "preferences.xml"
    tree = ET.parse(prefs)
    ET.SubElement(tree.getroot(), "group", {"id": "custom", "setting": "keep"})
    tree.write(prefs)

    platform_support.set_inkscape_python_preference("/new/python")

    root = ET.parse(prefs).getroot()
    assert root.find("group[@id='extensions']").get("python-interpreter") == "/new/python"
    assert root.find("group[@id='custom']").get("setting") == "keep"
    assert not platform_support.set_inkscape_python_preference("/new/python")["changed"]


def test_disabled_workaround_creates_no_preferences(macos_home, monkeypatch):
    monkeypatch.setenv("INKSCAPE_MCP_SET_PYTHON_PREF", "0")
    assert not platform_support.set_inkscape_python_preference()["changed"]
    assert not platform_support.live_profile_dir().exists()


def test_preference_diagnostics_do_not_create_profile(macos_home):
    status = platform_support.python_preference_status()
    assert status["exists"] is False
    assert not platform_support.live_profile_dir().exists()


@pytest.mark.parametrize("running", ["registered", "starting", "stopped"])
def test_launch_only_configures_stopped_managed_instance(macos_home, monkeypatch, running):
    executable = macos_home / "inkscape"
    executable.touch()
    preference = Mock()
    popen = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr(bus_manager, "is_macos", lambda: True)
    monkeypatch.setattr(bus_manager, "_inkscape_registered", lambda *args: running == "registered")
    monkeypatch.setattr(bus_manager, "_launched_pid", lambda: 42 if running == "starting" else None)
    monkeypatch.setattr(bus_manager, "_pid_alive", lambda *args: True)
    monkeypatch.setattr(bus_manager, "_wait_registered", lambda *args: True)
    monkeypatch.setattr(bus_manager, "STATE_DIR", macos_home)
    monkeypatch.setattr(bus_manager, "PID_FILE", macos_home / "pid")
    monkeypatch.setattr(bus_manager.subprocess, "Popen", popen)
    monkeypatch.setattr(platform_support, "set_inkscape_python_preference", preference)
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", str(macos_home / "normal"))

    assert bus_manager.ensure_inkscape("gdbus", "address", str(executable), "drawing.svg")
    if running == "stopped":
        preference.assert_called_once_with()
        env = popen.call_args.kwargs["env"]
        assert env["INKSCAPE_PROFILE_DIR"] == str(platform_support.live_profile_dir())
        assert popen.call_args.kwargs["start_new_session"] is True
    else:
        preference.assert_not_called()
        popen.assert_not_called()


def test_non_macos_live_profile_preserves_override(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_support, "is_macos", lambda: False)
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", str(tmp_path))
    assert platform_support.live_profile_dir() == tmp_path
