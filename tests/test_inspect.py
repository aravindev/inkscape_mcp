"""Unit tests for the inspect_* live ops — thin shims over the mcp_inspect extension.

Each op fixes a category and routes through invoke_extension. These tests mock
invoke_extension and assert wiring: spec shape, action name, success/failure
propagation, ok:false handling, and summary message content. The extension's
real inspection behaviour is exercised by its own test suite (not here).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkscape_mcp import extension_bridge
from inkscape_mcp.tools import live

EXTENSION_ACTION = "org.inkscape.mcp.inspect.noprefs"


def _ok(data: dict | None = None) -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=True, data=data or {"ok": True})


def _fail(error: str = "boom", stderr: str = "") -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=False, error=error, stderr=stderr)


@pytest.fixture
def mock_invoke(monkeypatch):
    """Patch invoke_extension as imported into tools.live."""
    mock = AsyncMock(return_value=_ok())
    monkeypatch.setattr(live, "invoke_extension", mock)
    return mock


async def _run(op_func, *, operation: str) -> dict:
    bus = MagicMock()
    return await op_func(bus, operation, time.perf_counter())


@pytest.mark.parametrize(
    "category, op_func, op_name",
    [
        ("selection", live._op_inspect_selection, "inspect_selection"),
        # get_selection is a thin alias for inspect_selection after Phase 3
        # cleanup — same extension call, same response shape.
        ("selection", live._op_get_selection, "get_selection"),
        ("layers", live._op_inspect_layers, "inspect_layers"),
        ("defs", live._op_inspect_defs, "inspect_defs"),
        ("view", live._op_inspect_view, "inspect_view"),
        ("pages", live._op_inspect_pages, "inspect_pages"),
    ],
)
async def test_each_category_dispatches_with_correct_spec(mock_invoke, category, op_func, op_name):
    res = await _run(op_func, operation=op_name)
    assert res["success"] is True
    mock_invoke.assert_awaited_once()
    args, kwargs = mock_invoke.call_args
    # Positional: (bus, action_name, spec). Keyword: timeout_s.
    assert args[1] == EXTENSION_ACTION
    assert args[2] == {"category": category}
    assert kwargs.get("timeout_s") == 10.0


async def test_extension_data_passes_through_unmodified(mock_invoke):
    payload = {
        "ok": True,
        "count": 2,
        "objects": [{"id": "a"}, {"id": "b"}],
        "extra": "field",
    }
    mock_invoke.return_value = _ok(payload)
    res = await _run(live._op_inspect_selection, operation="inspect_selection")
    assert res["success"] is True
    assert res["data"] == payload


async def test_selection_summary_includes_count(mock_invoke):
    mock_invoke.return_value = _ok({"ok": True, "count": 3, "objects": []})
    res = await _run(live._op_inspect_selection, operation="inspect_selection")
    assert res["success"] is True
    assert "3 object(s) selected" in res["message"]


async def test_layers_summary_counts_list(mock_invoke):
    mock_invoke.return_value = _ok({"ok": True, "layers": [{"id": "l1"}, {"id": "l2"}]})
    res = await _run(live._op_inspect_layers, operation="inspect_layers")
    assert res["success"] is True
    assert "2 layer(s)" in res["message"]


async def test_defs_summary_sums_known_buckets(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": True,
            "gradients": [{"id": "g1"}, {"id": "g2"}],
            "filters": [{"id": "f1"}],
            "markers": [],
            "patterns": [{"id": "p1"}],
            "clip_paths": [],
            "masks": [],
            "symbols": [{"id": "s1"}],
        }
    )
    res = await _run(live._op_inspect_defs, operation="inspect_defs")
    assert res["success"] is True
    assert "5 def(s) catalogued" in res["message"]


async def test_view_summary_includes_viewbox_and_zoom(mock_invoke):
    mock_invoke.return_value = _ok({"ok": True, "viewbox": "0 0 100 100", "zoom": 1.5})
    res = await _run(live._op_inspect_view, operation="inspect_view")
    assert res["success"] is True
    assert "0 0 100 100" in res["message"]
    assert "1.5" in res["message"]


async def test_pages_summary_includes_count(mock_invoke):
    mock_invoke.return_value = _ok({"ok": True, "count": 4, "pages": []})
    res = await _run(live._op_inspect_pages, operation="inspect_pages")
    assert res["success"] is True
    assert "4 page(s)" in res["message"]


async def test_extension_failure_propagates_error(mock_invoke):
    mock_invoke.return_value = _fail(error="bridge timeout")
    res = await _run(live._op_inspect_selection, operation="inspect_selection")
    assert res["success"] is False
    assert "bridge timeout" in res["message"]
    assert res["error"] == "bridge timeout"
    assert res["data"]["category"] == "selection"


async def test_extension_failure_includes_stderr(mock_invoke):
    mock_invoke.return_value = _fail(error="crash", stderr="Traceback: bad")
    res = await _run(live._op_inspect_layers, operation="inspect_layers")
    assert res["success"] is False
    assert "crash" in res["message"]
    assert "Traceback: bad" in res["message"]
    assert res["data"]["stderr"] == "Traceback: bad"


async def test_ok_false_from_extension_is_reported_as_failure(mock_invoke):
    mock_invoke.return_value = extension_bridge.ExchangeResult(
        success=True,
        data={"ok": False, "error": "unknown category"},
    )
    res = await _run(live._op_inspect_selection, operation="inspect_selection")
    assert res["success"] is False
    assert "unknown category" in res["message"]
    assert res["error"] == "unknown category"
    assert res["data"]["ok"] is False
