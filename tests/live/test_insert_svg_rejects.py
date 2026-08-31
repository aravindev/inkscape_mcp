"""`insert_svg` must not report success when it inserted nothing.

Two observed failures, both reporting `success: true, saved: true`:

* A bare fragment (no `<svg>` root) inserted nothing at all.
* Back-to-back inserts raced the clipboard. `xclip` daemonises, so `subprocess.run`
  returns before it owns the selection; the follow-up `paste-in-place` then pasted the
  *previous* payload. A third insert produced a duplicate of the second's rect and
  dropped its own circle entirely.
"""

from __future__ import annotations

from tests._helpers import payload as _payload


def _wrap(inner: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg">{inner}</svg>'


async def test_bare_fragment_is_accepted_or_refused_but_never_silently_dropped(mcp, live_doc):
    """A fragment without an <svg> wrapper must either be handled or rejected —
    what it must not do is report success while inserting nothing."""
    res = await mcp.call_tool(
        "inkscape_live",
        {
            "operation": "insert_svg",
            "payload": '<rect id="bare-probe" x="20" y="20" width="30" height="30" fill="#cc3333"/>',
        },
    )
    p = _payload(res)

    if p["success"]:
        found = await mcp.call_tool(
            "inkscape_live",
            {"operation": "inspect_element", "target": "bare-probe"},
        )
        assert _payload(found)["success"] is True, "reported success but nothing was inserted"
    else:
        assert p["message"], "a refusal must explain itself"


async def test_empty_payload_is_refused(mcp, live_doc):
    res = await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": "   "})
    assert _payload(res)["success"] is False


async def test_consecutive_inserts_each_land(mcp, live_doc):
    """Guards the stale-clipboard race: the second payload must not be a re-paste
    of the first."""
    first = _wrap('<rect id="race-a" x="10" y="10" width="20" height="20" fill="#cc3333"/>')
    second = _wrap('<circle id="race-b" cx="150" cy="60" r="15" fill="#3366cc"/>')

    assert _payload(await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": first}))["success"]
    assert _payload(await mcp.call_tool("inkscape_live", {"operation": "insert_svg", "payload": second}))["success"]

    for probe in ("race-a", "race-b"):
        res = await mcp.call_tool("inkscape_live", {"operation": "inspect_element", "target": probe})
        assert _payload(res)["success"] is True, f"{probe} was lost to a stale paste"
