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


async def test_rasterize_page_emits_export_page(fake_export, tmp_path, monkeypatch):
    async def three_pages(b, p):
        Path(p).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">'
            + '<inkscape:page x="0" y="0" width="1" height="1"/>' * 3
            + "</svg>"
        )

    monkeypatch.setattr(live, "_export_document_async", three_pages)
    monkeypatch.setattr(live, "_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    res = await live._op_rasterize(
        MagicMock(), "rasterize", "", json.dumps({"page": 3}), MagicMock(), _config_stub(tmp_path), time.perf_counter()
    )
    assert res["success"] is True, res
    assert "--export-page=3" in fake_export["argv"]
    assert res["data"]["page"] == 3
    # Inkscape truncates page-export paths at the first dot, so the CLI must be pointed
    # at a dot-free temp path and the PNG moved to the requested location afterwards.
    exported = next(a.split("=", 1)[1] for a in fake_export["argv"] if a.startswith("--export-filename="))
    assert "." not in exported.rsplit(".png", 1)[0]
    assert Path(res["data"]["path"]).exists()
    assert not Path(exported).parent.exists()


@pytest.mark.parametrize("payload", [{"page": 0}, {"page": "2"}, {"page": True}, {"page": 2, "area": "0:0:1:1"}])
async def test_rasterize_rejects_bad_page(fake_export, tmp_path, monkeypatch, payload):
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    res = await live._op_rasterize(
        MagicMock(), "rasterize", "", json.dumps(payload), MagicMock(), _config_stub(tmp_path), time.perf_counter()
    )
    assert res["success"] is False
    assert fake_export["argv"] is None


def test_blank_png_warning_detects_flat_images(tmp_path):
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(blank)
    clear = tmp_path / "clear.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(clear)
    art = tmp_path / "art.png"
    img = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
    img.putpixel((3, 3), (30, 110, 230, 255))
    img.save(art)

    assert "single flat colour" in live._blank_png_warning(blank)
    assert "fully transparent" in live._blank_png_warning(clear)
    assert live._blank_png_warning(art) is None
    assert live._blank_png_warning(tmp_path / "missing.png") is None


async def test_get_document_xml_large_returns_path_and_summary(tmp_path, monkeypatch):
    big = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
        ' xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" viewBox="0 0 10 10">'
        '<sodipodi:namedview><inkscape:page id="p1" x="0" y="0" width="10" height="10" inkscape:label="Uno"/>'
        "</sodipodi:namedview>"
        '<g id="capa" inkscape:label="Capa" style="display:none">' + "<rect/>" * 50 + "</g></svg>"
    )

    async def fake_export_async(b, p):
        Path(p).write_text(big)

    monkeypatch.setattr(live, "_export_document_async", fake_export_async)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")

    res = await live._op_get_document_xml(MagicMock(), "get_document_xml", json.dumps({"max_chars": 100}), time.perf_counter())
    assert res["success"] is True
    assert "xml" not in res["data"]
    summary = res["data"]["summary"]
    assert summary["pages"][0]["label"] == "Uno"
    assert summary["top_level"] == [{"tag": "g", "id": "capa", "label": "Capa", "hidden": True, "children": 50}]

    full = await live._op_get_document_xml(
        MagicMock(), "get_document_xml", json.dumps({"full": True, "max_chars": 100}), time.perf_counter()
    )
    assert full["data"]["xml"] == big

    small = await live._op_get_document_xml(MagicMock(), "get_document_xml", "", time.perf_counter())
    assert small["data"]["xml"] == big


def test_svg_is_complete(tmp_path):
    f = tmp_path / "s.svg"
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="a">')
    assert live._svg_is_complete(f) is False
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="a"/></svg>\n')
    assert live._svg_is_complete(f) is True
    assert live._svg_is_complete(tmp_path / "missing.svg") is False


async def test_export_waits_for_a_fully_written_snapshot(tmp_path, monkeypatch):
    """Inkscape fills the file after creating it; a half-written snapshot must not count."""
    from inkscape_mcp import extension_bridge

    monkeypatch.setattr(extension_bridge, "EXCHANGE_DIR", tmp_path / "exchange")
    snap = tmp_path / "snap.svg"

    def fake_trigger(bus, path):
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="half">')

        async def finish():
            await asyncio.sleep(0.3)
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="half"/></svg>')

        asyncio.get_running_loop().create_task(finish())

    monkeypatch.setattr(live, "_trigger_export", fake_trigger)
    await live._export_document_async(MagicMock(), snap)
    assert snap.read_text().endswith("</svg>")


async def test_rasterize_page_beyond_document_is_a_clear_error(tmp_path, monkeypatch):
    async def one_page_export(b, p):
        Path(p).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"'
            ' sodipodi:docname="live_doc.svg"/>'
        )

    monkeypatch.setattr(live, "_export_document_async", one_page_export)
    monkeypatch.setattr(live, "_scratch_path", lambda: tmp_path / "snap.svg")
    res = await live._op_rasterize(
        MagicMock(), "rasterize", "", json.dumps({"page": 2}), MagicMock(), _config_stub(tmp_path), time.perf_counter()
    )
    assert res["success"] is False
    assert res["error"] == "no such page"
    assert "live_doc.svg" in res["message"]
