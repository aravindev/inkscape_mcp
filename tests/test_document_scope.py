"""Document-scope routing in the live tools.

Inkscape 1.4 exports a few actions (undo, redo, vacuum-defs, page-move-*) only on
``/org/inkscape/Inkscape/document/N``; window-only ones (document-save, paste-in-place)
stay on ``/window/N``. The bus is mocked, so no Inkscape is needed.
"""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock

import pytest

from inkscape_mcp.tools import live


@pytest.fixture(autouse=True)
def no_action_descriptions(monkeypatch):
    live._ACTION_DESCRIPTIONS = None
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError("no inkscape")))
    yield
    live._ACTION_DESCRIPTIONS = None


def _bus(app, window, document, documents=(5,)):
    bus = MagicMock()
    bus.list_actions.side_effect = lambda scope, *a: {"app": app, "window": window, "document": document}[scope]
    bus.list_documents.return_value = list(documents)
    bus.list_windows.return_value = [1]
    return bus


def test_resolve_document_id_uses_the_only_document():
    assert live._resolve_document_id(_bus([], [], [], documents=[5])) == 5


@pytest.mark.parametrize("documents", [[], [1, 2]])
def test_resolve_document_id_refuses_none_or_several(documents):
    with pytest.raises(RuntimeError, match="exactly one open document"):
        live._resolve_document_id(_bus([], [], [], documents=documents))


def test_apply_action_falls_through_to_document_scope():
    bus = _bus(["select-all"], ["document-save"], ["undo", "select-all"])
    res = live._op_apply_action(bus, "apply_action", "undo", "", 1, time.perf_counter())
    assert res["success"] is True
    assert res["data"]["scope"] == "document"
    # The action goes to the document object; the follow-up save to the window.
    assert bus.activate.call_args_list[0].kwargs == {"scope": "document", "window_id": 5}
    assert bus.activate.call_args_list[1].args == ("document-save",)
    assert bus.activate.call_args_list[1].kwargs == {"scope": "window", "window_id": 1}


def test_apply_action_prefers_app_and_window_scope():
    bus = _bus(["select-all"], ["layer-new"], ["select-all", "layer-new"])
    res = live._op_apply_action(bus, "apply_action", "layer-new", "", 1, time.perf_counter())
    assert res["data"]["scope"] == "window"
    bus.list_documents.assert_not_called()


def test_apply_action_unknown_reports_why_document_scope_was_skipped():
    bus = _bus([], [], ["undo"], documents=[1, 2])
    res = live._op_apply_action(bus, "apply_action", "undo", "", 1, time.perf_counter())
    assert res["success"] is False
    assert res["error"] == "unknown action"
    assert "2 are open" in res["message"]
    bus.activate.assert_not_called()


async def test_list_actions_reports_document_only_actions():
    bus = _bus(["select-all", "vacuum-defs-x"], ["document-save"], ["select-all", "undo", "vacuum-defs"])
    res = await live._op_list_actions(bus, "list_actions", 1, "", time.perf_counter())
    assert [d["name"] for d in res["data"]["document"]] == ["undo", "vacuum-defs"]
    assert "2 document actions" in res["message"]


async def test_list_actions_filter_applies_to_document_actions():
    bus = _bus([], [], ["undo", "redo", "vacuum-defs"])
    res = await live._op_list_actions(bus, "list_actions", 1, "do", time.perf_counter())
    assert [d["name"] for d in res["data"]["document"]] == ["redo", "undo"]


async def test_list_actions_without_single_document_lists_none():
    bus = _bus(["select-all"], [], ["undo"], documents=[1, 2])
    res = await live._op_list_actions(bus, "list_actions", 1, "", time.perf_counter())
    assert res["success"] is True
    assert res["data"]["document"] == []
