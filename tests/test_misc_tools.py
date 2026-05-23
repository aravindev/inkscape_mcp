"""Prompts and resources discovery."""

from __future__ import annotations


async def test_list_prompts(mcp):
    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    # Five workflow prompts are registered by register_prompts_and_resources().
    assert len(names) >= 1, f"no prompts registered: {names}"


async def test_list_resources(mcp):
    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert any("capabilities" in u for u in uris), uris
