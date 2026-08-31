"""Operations must refuse arguments they cannot honour.

Two failure modes are covered:

* Page-scoped ops (`page_rotate`, `set_document_units`, ...) accepted `object_id` and
  silently ignored it — the caller believes the change was scoped when it was not.
* Exactly-N ops (`path_division`, `path_cut`) need a precise number of selected objects.
  Given the wrong count they used to no-op and report success.

Refusing is the honest outcome in both cases; the message has to say why.
"""

from __future__ import annotations

import pytest

from tests._helpers import payload as _payload


async def test_page_scoped_op_rejects_object_id(mcp, minimal_svg, tmp_path):
    out = tmp_path / "rotated.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "page_rotate",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "steps": 1,
            "object_id": "rect-1",
        },
    )
    p = _payload(res)

    assert p["success"] is False, "page_rotate cannot be scoped to an object"
    assert "page_rotate" in p["message"]
    assert "object_id" in p["message"], f"the message must name the offending argument: {p['message']}"


async def test_page_scoped_op_still_works_without_ids(mcp, minimal_svg, tmp_path):
    """The refusal must be about the argument, not a regression of the operation."""
    out = tmp_path / "rotated_ok.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "page_rotate",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "steps": 1,
        },
    )
    assert _payload(res)["success"] is True


@pytest.mark.parametrize("ids", [["path-a"], ["path-a", "path-b", "path-a"]])
async def test_exactly_two_op_rejects_wrong_count(mcp, multi_path_svg, tmp_path, ids):
    out = tmp_path / f"cut_{len(ids)}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_cut",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_ids": ids,
        },
    )
    p = _payload(res)

    assert p["success"] is False, f"path_cut needs exactly 2 objects, got {len(ids)}"
    assert "2" in p["message"], f"the message must name the required count: {p['message']}"
