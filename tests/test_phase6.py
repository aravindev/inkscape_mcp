"""Unit tests for Phase 6 analytical primitives — inspect_element,
execute_inkex, rasterize. The extensions themselves run inside Inkscape
(not unit-testable per project policy); we mock invoke_extension and
verify the dispatch + spec shape on the MCP side."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkscape_mcp import extension_bridge
from inkscape_mcp.tools import live

EXT_INSPECT = "org.inkscape.mcp.inspect.noprefs"
EXT_EXECUTE = "org.inkscape.mcp.execute.noprefs"


def _ok(data: dict) -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=True, data=data)


def _fail(error: str = "boom", stderr: str = "") -> extension_bridge.ExchangeResult:
    return extension_bridge.ExchangeResult(success=False, error=error, stderr=stderr)


@pytest.fixture
def mock_invoke(monkeypatch):
    mock = AsyncMock(return_value=_ok({"ok": True}))
    monkeypatch.setattr(live, "invoke_extension", mock)
    return mock


# ---------------------------------------------------------------------------
# inspect_element
# ---------------------------------------------------------------------------


async def test_inspect_element_passes_target_in_spec(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": True,
            "category": "element",
            "id": "r1",
            "tag": "rect",
            "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "computed_style": {"fill": "#ff0000"},
            "attributes": {"id": "r1"},
            "ancestors": [],
        }
    )
    bus = MagicMock()
    res = await live._op_inspect_element(bus, "inspect_element", "r1", time.perf_counter())
    assert res["success"] is True
    spec = mock_invoke.call_args.args[2]
    assert spec == {"category": "element", "target": "r1"}
    assert mock_invoke.call_args.args[1] == EXT_INSPECT


async def test_inspect_element_summary_includes_id_tag_bbox(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": True,
            "category": "element",
            "id": "p1",
            "tag": "path",
            "bbox": {"x": 100, "y": 200, "w": 50, "h": 40},
            "computed_style": {},
            "attributes": {},
            "ancestors": [],
        }
    )
    bus = MagicMock()
    res = await live._op_inspect_element(bus, "inspect_element", "p1", time.perf_counter())
    assert "<path>" in res["message"]
    assert "id=p1" in res["message"]
    assert "100" in res["message"] and "200" in res["message"]


async def test_inspect_element_missing_target_fails(mock_invoke):
    bus = MagicMock()
    res = await live._op_inspect_element(bus, "inspect_element", "", time.perf_counter())
    assert res["success"] is False
    assert "target" in res["message"].lower()
    mock_invoke.assert_not_awaited()


async def test_inspect_element_unknown_id_propagates_error(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": False,
            "category": "element",
            "error": "no element with id 'zzz'",
        }
    )
    bus = MagicMock()
    res = await live._op_inspect_element(bus, "inspect_element", "zzz", time.perf_counter())
    assert res["success"] is False
    assert "no element" in res["message"]


# ---------------------------------------------------------------------------
# execute_inkex
# ---------------------------------------------------------------------------


async def test_execute_inkex_sends_python_code(mock_invoke):
    mock_invoke.return_value = _ok({"ok": True, "result": [1, 2, 3]})
    bus = MagicMock()
    code = "result = [p.get('id') for p in svg.iter() if p.tag.endswith('}path')]"
    res = await live._op_execute_inkex(bus, "execute_inkex", code, time.perf_counter())
    assert res["success"] is True
    assert res["data"]["result"] == [1, 2, 3]
    spec = mock_invoke.call_args.args[2]
    assert spec == {"python_code": code}
    assert mock_invoke.call_args.args[1] == EXT_EXECUTE
    assert mock_invoke.call_args.kwargs.get("timeout_s") == 30.0


async def test_execute_inkex_missing_payload_fails(mock_invoke):
    bus = MagicMock()
    res = await live._op_execute_inkex(bus, "execute_inkex", "", time.perf_counter())
    assert res["success"] is False
    assert "payload" in res["message"].lower()
    mock_invoke.assert_not_awaited()


async def test_execute_inkex_extension_failure_includes_stderr(mock_invoke):
    mock_invoke.return_value = _fail(error="bridge timeout", stderr="...trace...")
    bus = MagicMock()
    res = await live._op_execute_inkex(bus, "execute_inkex", "x = 1", time.perf_counter())
    assert res["success"] is False
    assert "bridge timeout" in res["message"]
    assert "...trace..." in res["message"]


async def test_execute_inkex_ok_false_includes_traceback(mock_invoke):
    mock_invoke.return_value = _ok(
        {
            "ok": False,
            "error": "NameError: name 'foo' is not defined",
            "traceback": "Traceback (most recent call last):\n  File ...",
        }
    )
    bus = MagicMock()
    res = await live._op_execute_inkex(bus, "execute_inkex", "foo()", time.perf_counter())
    assert res["success"] is False
    assert "NameError" in res["message"]
    assert "Traceback" in res["message"]


# ---------------------------------------------------------------------------
# rasterize
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_export(monkeypatch, tmp_path):
    """Stub the document export so we don't touch real Inkscape, and fake the async
    subprocess so we can assert the CLI argv and pretend a PNG was written.

    Rasterize runs on the request path, so it uses asyncio.create_subprocess_exec rather
    than a blocking subprocess.run — the stub has to match that shape.
    """

    async def fake_export_async(b, p):
        Path(p).write_text("<svg/>")

    monkeypatch.setattr(live, "_export_document_async", fake_export_async)

    calls = {"argv": None, "output_path": None, "returncode": 0, "stderr": b""}

    async def fake_exec(*argv, **kwargs):
        calls["argv"] = list(argv)
        if calls["returncode"] == 0:
            # Find --export-filename and write a tiny "PNG" so the existence check passes.
            for a in argv:
                if a.startswith("--export-filename="):
                    out = Path(a.split("=", 1)[1])
                    out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
                    calls["output_path"] = out

        proc = MagicMock()
        proc.returncode = calls["returncode"]

        async def communicate():
            return b"", calls["stderr"]

        proc.communicate = communicate
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def _config_stub(tmp_path):
    cfg = MagicMock()
    cfg.inkscape_executable = "/usr/bin/inkscape"
    return cfg


async def test_rasterize_full_canvas_default(fake_export, tmp_path, monkeypatch):
    # Direct scratch dir to tmp so we don't litter the user's cache.
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(bus, "rasterize", "", "", cli, cfg, time.perf_counter())
    assert res["success"] is True, res
    argv = fake_export["argv"]
    assert "/usr/bin/inkscape" in argv[0]
    assert any(a == "--export-type=png" for a in argv)
    # No --export-id when target is empty.
    assert not any(a.startswith("--export-id=") for a in argv)
    assert res["data"]["path"].endswith(".png")
    assert res["data"]["bytes"] > 0


async def test_rasterize_with_target_id_emits_export_id_only(fake_export, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(bus, "rasterize", "my-elem", "", cli, cfg, time.perf_counter())
    assert res["success"] is True
    argv = fake_export["argv"]
    assert "--export-id=my-elem" in argv
    assert "--export-id-only" in argv
    assert res["data"]["target"] == "my-elem"


async def test_rasterize_area_and_dpi(fake_export, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(
        bus,
        "rasterize",
        "",
        json.dumps({"area": "0:0:100:100", "dpi": 192}),
        cli,
        cfg,
        time.perf_counter(),
    )
    assert res["success"] is True
    argv = fake_export["argv"]
    assert "--export-area=0:0:100:100" in argv
    assert any(a.startswith("--export-dpi=192") for a in argv)


async def test_rasterize_rejects_bad_area_format(fake_export, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(
        bus,
        "rasterize",
        "",
        json.dumps({"area": "0,0,100,100"}),
        cli,
        cfg,
        time.perf_counter(),
    )
    assert res["success"] is False
    assert "area must be" in res["message"]


async def test_rasterize_rejects_bad_dpi(fake_export, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(
        bus,
        "rasterize",
        "",
        json.dumps({"dpi": "huge"}),
        cli,
        cfg,
        time.perf_counter(),
    )
    assert res["success"] is False
    assert "dpi" in res["message"]


async def test_rasterize_rejects_relative_filename(fake_export, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(
        bus,
        "rasterize",
        "",
        json.dumps({"filename": "rel/out.png"}),
        cli,
        cfg,
        time.perf_counter(),
    )
    assert res["success"] is False
    assert "absolute" in res["message"]


async def test_rasterize_missing_cli_wrapper_fails(monkeypatch):
    bus = MagicMock()
    res = await live._op_rasterize(bus, "rasterize", "", "", None, None, time.perf_counter())
    assert res["success"] is False
    assert "cli_wrapper" in res["message"] or "dependencies" in res["error"].lower()


async def test_rasterize_subprocess_failure_propagates(fake_export, monkeypatch, tmp_path):
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    fake_export["returncode"] = 1
    fake_export["stderr"] = b"export failed: bad input"

    bus = MagicMock()
    cli = MagicMock()
    cfg = _config_stub(tmp_path)
    res = await live._op_rasterize(bus, "rasterize", "", "", cli, cfg, time.perf_counter())
    assert res["success"] is False
    assert "rc=1" in res["message"]
    assert "bad input" in res["message"]
