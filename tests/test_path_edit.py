"""Unit tests for the path_edit live op — routes per-node bezier ops through
the mcp_path_edit extension.

Mocks invoke_extension and asserts wiring: payload validation, spec shape sent
to the extension, success/failure propagation, ok:false handling, and auto-save
behaviour. The extension's real path-math is exercised in its own helpers (see
plugins/mcp_path_edit.py); these tests only cover the MCP-side dispatch.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkscape_mcp import extension_bridge
from inkscape_mcp.tools import live

EXTENSION_ACTION = "org.inkscape.mcp.path-edit.noprefs"


def _ok(data: dict | None = None) -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(
        success=True,
        data=data or {"ok": True, "d": "M 0 0", "summary": "ok"},
    )


def _fail(error: str = "boom", stderr: str = "") -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=False, error=error, stderr=stderr)


@pytest.fixture
def mock_invoke(monkeypatch):
    mock = AsyncMock(return_value=_ok())
    monkeypatch.setattr(live, "invoke_extension", mock)
    return mock


@pytest.fixture(autouse=True)
def disable_autosave(monkeypatch):
    """Don't trigger document-save in unit tests — the bus is a MagicMock."""
    monkeypatch.setenv("INKSCAPE_MCP_AUTO_SAVE", "0")


async def _run(target: str, payload: dict | str) -> dict:
    bus = MagicMock()
    payload_json = payload if isinstance(payload, str) else json.dumps(payload)
    return await live._op_path_edit(bus, "path_edit", target, payload_json, 1, time.perf_counter())


async def test_dispatches_with_path_id_and_op(mock_invoke):
    res = await _run("p1", {"op": "move_node", "node": [0, 1], "to": [5, 5]})
    assert res["success"] is True
    mock_invoke.assert_awaited_once()
    args, kwargs = mock_invoke.call_args
    assert args[1] == EXTENSION_ACTION
    spec = args[2]
    assert spec["path_id"] == "p1"
    assert spec["op"] == "move_node"
    assert spec["node"] == [0, 1]
    assert spec["to"] == [5, 5]
    assert kwargs.get("timeout_s") == 15.0


@pytest.mark.parametrize(
    "sub_op",
    ["move_node", "set_handle_in", "set_handle_out", "insert_node", "smooth", "cusp", "subdivide"],
)
async def test_each_sub_op_accepted(mock_invoke, sub_op):
    res = await _run("p1", {"op": sub_op})
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec["op"] == sub_op


async def test_missing_target_rejected(mock_invoke):
    res = await _run("", {"op": "move_node"})
    assert res["success"] is False
    assert "target" in res["message"].lower()
    mock_invoke.assert_not_awaited()


async def test_unknown_op_rejected(mock_invoke):
    res = await _run("p1", {"op": "teleport"})
    assert res["success"] is False
    assert "unknown path_edit op" in res["message"]
    assert "teleport" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_invalid_json_payload_rejected(mock_invoke):
    res = await _run("p1", "{not json")
    assert res["success"] is False
    assert "not valid JSON" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_non_object_payload_rejected(mock_invoke):
    res = await _run("p1", "[1, 2]")
    assert res["success"] is False
    assert "JSON object" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_extension_failure_propagates(mock_invoke):
    mock_invoke.return_value = _fail(error="bridge timeout")
    res = await _run("p1", {"op": "move_node"})
    assert res["success"] is False
    assert "bridge timeout" in res["message"]
    assert res["error"] == "bridge timeout"
    assert res["data"]["op"] == "move_node"
    assert res["data"]["path_id"] == "p1"


async def test_extension_failure_includes_stderr(mock_invoke):
    mock_invoke.return_value = _fail(error="crash", stderr="Traceback: oops")
    res = await _run("p1", {"op": "smooth"})
    assert res["success"] is False
    assert "crash" in res["message"]
    assert "Traceback: oops" in res["message"]
    assert res["data"]["stderr"] == "Traceback: oops"


async def test_ok_false_from_extension_reports_failure(mock_invoke):
    mock_invoke.return_value = extension_bridge.ExchangeResult(
        success=True,
        data={"ok": False, "error": "node (0, 9) out of range"},
    )
    res = await _run("p1", {"op": "move_node"})
    assert res["success"] is False
    assert "out of range" in res["message"]
    assert res["error"] == "node (0, 9) out of range"


async def test_success_response_carries_d_and_summary(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": True,
            "op": "move_node",
            "path_id": "p1",
            "d": "M 0 0 L 5 5",
            "summary": "moved node (0,1) by (5.000,5.000)",
        }
    )
    res = await _run("p1", {"op": "move_node", "node": [0, 1], "to": [5, 5]})
    assert res["success"] is True
    assert "moved node" in res["message"]
    assert res["data"]["d"] == "M 0 0 L 5 5"
    assert res["data"]["op"] == "move_node"
    assert res["data"]["path_id"] == "p1"


async def test_auto_save_skipped_when_env_is_zero(mock_invoke):
    # Fixture already sets INKSCAPE_MCP_AUTO_SAVE=0
    bus = MagicMock()
    res = await live._op_path_edit(
        bus,
        "path_edit",
        "p1",
        json.dumps({"op": "move_node", "node": [0, 0], "to": [1, 1]}),
        1,
        time.perf_counter(),
    )
    assert res["success"] is True
    assert res["data"]["saved"] is False
    bus.activate.assert_not_called()


async def test_auto_save_fires_document_save(monkeypatch):
    monkeypatch.delenv("INKSCAPE_MCP_AUTO_SAVE", raising=False)
    mock = AsyncMock(return_value=_ok())
    monkeypatch.setattr(live, "invoke_extension", mock)
    bus = MagicMock()
    res = await live._op_path_edit(
        bus,
        "path_edit",
        "p1",
        json.dumps({"op": "smooth", "node": [0, 0]}),
        1,
        time.perf_counter(),
    )
    assert res["success"] is True
    assert res["data"]["saved"] is True
    bus.activate.assert_called_with("document-save", scope="window", window_id=1)
