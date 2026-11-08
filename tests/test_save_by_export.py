"""Live auto-save where `document-save` is unreachable (macOS exports no /window/N).

The save exports the active document with app-scope export-* actions and writes it over
the file the MCP opened, matched by `sodipodi:docname`. Without exactly one match it
refuses and writes nothing.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from inkscape_mcp import bus_manager
from inkscape_mcp.tools import live

_EXPORTED = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
    'sodipodi:docname="{docname}"><rect id="probe"/></svg>'
)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.delenv("INKSCAPE_MCP_AUTO_SAVE", raising=False)
    monkeypatch.setattr(bus_manager, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(bus_manager, "OPENED_PATHS_FILE", tmp_path / "state" / "opened_paths.json")
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path / "scratch")


def _bus(docname: str, window_actions=("undo", "redo")) -> MagicMock:
    """A gdbus-like bus with no document-save; export-do writes the export file."""
    bus = MagicMock()
    bus.list_windows.return_value = [1]
    bus.list_actions.return_value = list(window_actions)
    state: dict = {}

    def activate(action, args=None, scope="app", window_id=1):
        if action == "export-filename":
            state["path"] = args[0]
        if action == "export-do":
            Path(state["path"]).write_text(_EXPORTED.format(docname=docname), encoding="utf-8")

    bus.activate.side_effect = activate
    return bus


def _doc(tmp_path: Path, name: str = "drawing.svg") -> Path:
    path = tmp_path / "docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<svg/>", encoding="utf-8")
    return path


async def test_saves_by_exporting_over_the_opened_file(tmp_path):
    doc = _doc(tmp_path)
    bus_manager.record_opened_path(str(doc))
    bus = _bus("drawing.svg")

    saved, reason = await live._save_active_document(bus, 1)

    assert (saved, reason) == (True, "")
    assert 'id="probe"' in doc.read_text(encoding="utf-8")
    actions = [c.args[0] for c in bus.activate.call_args_list]
    assert actions == ["export-filename", "export-type", "export-overwrite", "export-do"]
    assert all(c.kwargs["scope"] == "app" for c in bus.activate.call_args_list)
    assert bus.activate.call_args_list[1].args[1] == ["svg"]
    assert "document-save" not in actions


async def test_document_save_is_used_when_the_window_offers_it(tmp_path):
    doc = _doc(tmp_path)
    bus_manager.record_opened_path(str(doc))
    bus = _bus("drawing.svg", window_actions=("document-save",))

    saved, _ = await live._save_active_document(bus, 1)

    assert saved is True
    bus.activate.assert_called_once_with("document-save", scope="window", window_id=1)
    assert doc.read_text(encoding="utf-8") == "<svg/>"


async def test_refuses_a_file_the_mcp_did_not_open(tmp_path):
    doc = _doc(tmp_path)
    bus = _bus("drawing.svg")

    saved, reason = await live._save_active_document(bus, 1)

    assert saved is False
    assert "not opened through the MCP" in reason
    assert doc.read_text(encoding="utf-8") == "<svg/>"


async def test_refuses_when_the_file_name_is_ambiguous(tmp_path):
    first = _doc(tmp_path / "a")
    second = _doc(tmp_path / "b")
    bus_manager.record_opened_path(str(first))
    bus_manager.record_opened_path(str(second))
    bus = _bus("drawing.svg")

    saved, reason = await live._save_active_document(bus, 1)

    assert saved is False
    assert "several opened files" in reason
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8") == "<svg/>"


async def test_refuses_a_document_without_a_file_name(tmp_path):
    bus_manager.record_opened_path(str(_doc(tmp_path)))
    bus = _bus("")

    saved, reason = await live._save_active_document(bus, 1)

    assert saved is False
    assert "no file name" in reason


async def test_kill_switch_skips_the_export(monkeypatch, tmp_path):
    monkeypatch.setenv("INKSCAPE_MCP_AUTO_SAVE", "0")
    bus = _bus("drawing.svg")

    saved, _ = await live._save_active_document(bus, 1)

    assert saved is False
    bus.activate.assert_not_called()


def test_opened_paths_dedupe_and_skip_missing_files(tmp_path):
    doc = _doc(tmp_path)
    gone = tmp_path / "docs" / "gone.svg"
    bus_manager.record_opened_path(str(doc))
    bus_manager.record_opened_path(str(gone))
    bus_manager.record_opened_path(str(doc))

    assert bus_manager.opened_paths_named("drawing.svg") == [str(doc.resolve())]
    assert bus_manager.opened_paths_named("gone.svg") == []
    assert bus_manager.opened_paths_named("") == []


def test_open_file_records_the_path_on_managed_platforms(monkeypatch, tmp_path):
    doc = _doc(tmp_path)
    monkeypatch.setattr(bus_manager, "manages_bus", lambda: True)

    res = live._op_open_file(MagicMock(), "open_file", str(doc), time.perf_counter())

    assert res["success"] is True
    assert bus_manager.opened_paths_named("drawing.svg") == [str(doc.resolve())]


def test_managed_launch_records_the_opened_document(monkeypatch, tmp_path):
    doc = _doc(tmp_path)
    exe = tmp_path / "inkscape"
    exe.write_text("")
    monkeypatch.setattr(bus_manager, "_inkscape_registered", lambda *a: False)
    monkeypatch.setattr(bus_manager, "_launched_pid", lambda: None)
    monkeypatch.setattr(bus_manager, "_wait_registered", lambda *a: True)
    monkeypatch.setattr(bus_manager, "PID_FILE", tmp_path / "inkscape.pid")
    monkeypatch.setattr(bus_manager.platform_support, "set_inkscape_python_preference", lambda *a: {})
    monkeypatch.setattr(bus_manager.subprocess, "Popen", lambda argv, **kw: Mock(pid=1))

    assert bus_manager.ensure_inkscape(None, "unix:path=/x", str(exe), open_path=str(doc))
    assert bus_manager.opened_paths_named("drawing.svg") == [str(doc.resolve())]
