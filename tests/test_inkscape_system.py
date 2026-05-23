"""Smoke + system tool tests."""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload


async def test_list_tools(mcp):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"inkscape_file", "inkscape_vector", "inkscape_analysis", "inkscape_system"} <= names


@pytest.mark.parametrize(
    "op",
    ["status", "help", "diagnostics", "version", "config", "list_extensions"],
)
async def test_system_operation_returns_payload(mcp, op):
    res = await mcp.call_tool("inkscape_system", {"operation": op})
    payload = _payload(res)
    assert payload, f"Empty payload for inkscape_system({op})"
    assert payload.get("success") is True, f"Operation {op} failed: {payload}"


async def test_diagnostics_reports_inkscape(mcp):
    res = await mcp.call_tool("inkscape_system", {"operation": "diagnostics"})
    payload = _payload(res)
    # Inkscape was located by the detector — diagnostics must reflect that somewhere.
    serialized = str(payload).lower()
    assert "inkscape" in serialized
