"""Unit tests for _op_edit_xml — the extension-dispatching edit_xml op.

The op is a thin shim: validate inputs, build a spec, hand off to
invoke_extension, propagate the result. These tests mock invoke_extension
and assert on the spec shape and error handling. File-on-disk mutation
behaviour is now the extension's responsibility (see the inkex test suite).
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkscape_mcp import extension_bridge
from inkscape_mcp.tools import live

EXTENSION_ACTION = "org.inkscape.mcp.edit-xml.noprefs"


def _ok(data: dict | None = None) -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=True, data=data or {"affected": 1})


def _fail(error: str = "boom", stderr: str = "") -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=False, error=error, stderr=stderr)


@pytest.fixture
def mock_invoke(monkeypatch):
    """Patch invoke_extension as imported into tools.live."""
    mock = AsyncMock(return_value=_ok())
    monkeypatch.setattr(live, "invoke_extension", mock)
    return mock


async def _run(target: str, payload: str) -> dict:
    bus = MagicMock()
    return await live._op_edit_xml(bus, "edit_xml", target, payload, 1, time.perf_counter())


async def test_append_dispatches_spec_to_extension(mock_invoke):
    res = await _run(
        "//svg:defs",
        json.dumps({"action": "append", "xml": '<filter id="x"/>'}),
    )
    assert res["success"] is True
    assert res["data"]["affected"] == 1
    mock_invoke.assert_awaited_once()
    args, kwargs = mock_invoke.call_args
    # Positional: (bus, action_name, spec). Keyword: timeout_s.
    assert args[1] == EXTENSION_ACTION
    assert args[2] == {"xpath": "//svg:defs", "action": "append", "xml": '<filter id="x"/>'}
    assert kwargs.get("timeout_s") == 15.0


async def test_set_attr_spec_includes_name_and_value(mock_invoke):
    res = await _run(
        '//svg:rect[@id="r1"]',
        json.dumps({"action": "set_attr", "name": "fill", "value": "green"}),
    )
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec == {
        "xpath": '//svg:rect[@id="r1"]',
        "action": "set_attr",
        "name": "fill",
        "value": "green",
    }


async def test_set_text_spec_includes_text(mock_invoke):
    res = await _run(
        '//svg:text[@id="t1"]',
        json.dumps({"action": "set_text", "text": "new"}),
    )
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec == {"xpath": '//svg:text[@id="t1"]', "action": "set_text", "text": "new"}


async def test_remove_spec_omits_optional_fields(mock_invoke):
    res = await _run('//svg:rect[@id="r2"]', json.dumps({"action": "remove"}))
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec == {"xpath": '//svg:rect[@id="r2"]', "action": "remove"}


@pytest.mark.parametrize(
    "action",
    ["insert_before", "insert_after", "replace"],
)
async def test_insert_and_replace_actions_pass_xml(mock_invoke, action):
    res = await _run(
        '//svg:rect[@id="r1"]',
        json.dumps({"action": action, "xml": '<circle r="5"/>'}),
    )
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec["action"] == action
    assert spec["xml"] == '<circle r="5"/>'


async def test_affected_count_reflected_in_message(mock_invoke):
    mock_invoke.return_value = _ok({"affected": 3})
    res = await _run("//svg:rect", json.dumps({"action": "set_attr", "name": "o", "value": "1"}))
    assert res["success"] is True
    assert "3 node(s)" in res["message"]
    assert "set_attr" in res["message"]
    assert res["data"]["affected"] == 3


async def test_extra_extension_data_passes_through(mock_invoke):
    mock_invoke.return_value = _ok({"affected": 2, "ids": ["a", "b"]})
    res = await _run("//svg:rect", json.dumps({"action": "remove"}))
    assert res["data"]["affected"] == 2
    assert res["data"]["ids"] == ["a", "b"]


async def test_empty_target_rejected_before_invoke(mock_invoke):
    res = await _run("", json.dumps({"action": "remove"}))
    assert res["success"] is False
    assert "target" in res["message"].lower()
    mock_invoke.assert_not_awaited()


async def test_unknown_action_rejected_before_invoke(mock_invoke):
    res = await _run("//svg:defs", json.dumps({"action": "frobnicate"}))
    assert res["success"] is False
    assert "unknown action" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_missing_action_rejected_before_invoke(mock_invoke):
    res = await _run("//svg:defs", json.dumps({"xml": "<x/>"}))
    assert res["success"] is False
    assert "unknown action" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_malformed_json_rejected_before_invoke(mock_invoke):
    res = await _run("//svg:defs", "{not valid json")
    assert res["success"] is False
    assert "valid JSON" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_non_object_payload_rejected_before_invoke(mock_invoke):
    res = await _run("//svg:defs", json.dumps(["a", "list"]))
    assert res["success"] is False
    assert "JSON object" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_empty_payload_treated_as_empty_object(mock_invoke):
    # No 'action' present, so this should fail validation (not crash).
    res = await _run("//svg:defs", "")
    assert res["success"] is False
    assert "unknown action" in res["message"]
    mock_invoke.assert_not_awaited()


async def test_extension_failure_propagates_error(mock_invoke):
    mock_invoke.return_value = _fail(error="xpath matched no nodes")
    res = await _run("//svg:none", json.dumps({"action": "remove"}))
    assert res["success"] is False
    assert "xpath matched no nodes" in res["message"]
    assert res["error"] == "xpath matched no nodes"


async def test_extension_failure_includes_stderr_when_present(mock_invoke):
    mock_invoke.return_value = _fail(error="crash", stderr="Traceback: boom")
    res = await _run("//svg:defs", json.dumps({"action": "remove"}))
    assert res["success"] is False
    assert "crash" in res["message"]
    assert "Traceback: boom" in res["message"]
    assert res["data"]["stderr"] == "Traceback: boom"


async def test_extension_failure_without_error_has_fallback_message(mock_invoke):
    mock_invoke.return_value = extension_bridge.ExchangeResult(success=False)
    res = await _run("//svg:defs", json.dumps({"action": "remove"}))
    assert res["success"] is False
    assert res["message"]  # non-empty fallback
