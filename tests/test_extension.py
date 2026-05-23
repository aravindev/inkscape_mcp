"""Unit tests for the inkscape_extension tool.

Covers INX parsing, discovery, command construction, and the four operations
(list / describe / run / run_live). Subprocess invocation is mocked — the
real headless invocation of system extensions is left to an opt-in live test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from lxml import etree

from inkscape_mcp.tools import extension as ext_tool

# ---------------------------------------------------------------------------
# INX fixture factory
# ---------------------------------------------------------------------------


def _write_inx(
    dir_path: Path,
    *,
    ext_id: str,
    name: str = "Test Extension",
    script: str | None = "test_ext.py",
    interpreter: str = "python",
    params: list[dict] | None = None,
    category: str | None = None,
) -> Path:
    """Write a minimal INX file. Optionally write a stub script alongside it."""
    params_xml = ""
    for p in params or []:
        opts = "".join(f'<option value="{o}">{o}</option>' for o in p.get("options", []))
        params_xml += (
            f'<param name="{p["name"]}" type="{p.get("type", "string")}" '
            f'gui-text="{p.get("desc", "")}">'
            f"{p.get('default', '')}{opts}</param>"
        )
    submenu = f'<effects-menu><submenu name="{category}">{category}</submenu></effects-menu>' if category else ""
    script_block = (
        f'<script><command location="inx" interpreter="{interpreter}">{script}</command></script>' if script else ""
    )
    inx_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<inkscape-extension xmlns="http://www.inkscape.org/namespace/inkscape/extension">
    <name>{name}</name>
    <id>{ext_id}</id>
    <effect>
        <object-type>all</object-type>
        {submenu}
    </effect>
    {script_block}
    {params_xml}
</inkscape-extension>"""
    inx_path = dir_path / f"{ext_id}.inx"
    inx_path.write_text(inx_xml)
    if script:
        (dir_path / script).write_text("#!/usr/bin/env python\n# stub\n")
    return inx_path


@pytest.fixture
def fake_ext_dirs(tmp_path, monkeypatch):
    """Point the extension tool at a temp dir as the system ext path, and clear cache."""
    system = tmp_path / "system_exts"
    user = tmp_path / "user_exts"
    system.mkdir()
    user.mkdir()
    monkeypatch.setattr(ext_tool, "_SYSTEM_EXT_DIRS", (system, Path("/nonexistent/path")))
    monkeypatch.setattr(ext_tool, "_USER_EXT_DIR", user)
    monkeypatch.setattr(ext_tool, "_CACHE", None)
    return system, user


# ---------------------------------------------------------------------------
# INX parsing
# ---------------------------------------------------------------------------


def test_parse_inx_extracts_id_name_script(fake_ext_dirs):
    system, _ = fake_ext_dirs
    inx = _write_inx(system, ext_id="org.test.basic", name="Basic")
    ext = ext_tool._parse_inx(inx, source="system")
    assert ext is not None
    assert ext.id == "org.test.basic"
    assert ext.name == "Basic"
    assert ext.interpreter == "python"
    assert ext.script_path == (system / "test_ext.py").resolve()


def test_parse_inx_collects_params_with_metadata(fake_ext_dirs):
    system, _ = fake_ext_dirs
    inx = _write_inx(
        system,
        ext_id="org.test.params",
        params=[
            {"name": "size", "type": "int", "default": "10", "desc": "Size"},
            {"name": "shape", "type": "optiongroup", "options": ["circle", "square"]},
        ],
    )
    ext = ext_tool._parse_inx(inx, source="system")
    by_name = {p.name: p for p in ext.params}
    assert by_name["size"].type == "int"
    assert by_name["size"].default == "10"
    assert by_name["size"].description == "Size"
    assert by_name["shape"].options == ["circle", "square"]


def test_parse_inx_returns_none_for_malformed_xml(tmp_path):
    bad = tmp_path / "bad.inx"
    bad.write_text("<not really xml")
    assert ext_tool._parse_inx(bad, source="system") is None


def test_parse_inx_returns_none_when_no_id(fake_ext_dirs):
    system, _ = fake_ext_dirs
    no_id = system / "no_id.inx"
    no_id.write_text(
        '<inkscape-extension xmlns="http://www.inkscape.org/namespace/inkscape/extension">'
        "<name>X</name></inkscape-extension>"
    )
    assert ext_tool._parse_inx(no_id, source="system") is None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_finds_extensions_in_both_dirs(fake_ext_dirs):
    system, user = fake_ext_dirs
    _write_inx(system, ext_id="org.test.sys")
    _write_inx(user, ext_id="org.test.usr")
    catalog = ext_tool._discover()
    assert "org.test.sys" in catalog
    assert "org.test.usr" in catalog
    assert catalog["org.test.sys"].source == "system"
    assert catalog["org.test.usr"].source == "user"


def test_discover_user_overrides_system(fake_ext_dirs):
    system, user = fake_ext_dirs
    _write_inx(system, ext_id="org.test.shadow", name="SystemVersion")
    _write_inx(user, ext_id="org.test.shadow", name="UserVersion")
    catalog = ext_tool._discover()
    assert catalog["org.test.shadow"].name == "UserVersion"
    assert catalog["org.test.shadow"].source == "user"


def test_discover_cache_avoids_rescan(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.cached")
    ext_tool._discover()
    # Add a new file after first scan — without refresh, shouldn't appear.
    _write_inx(system, ext_id="org.test.late")
    second = ext_tool._discover()
    assert "org.test.late" not in second
    third = ext_tool._discover(refresh=True)
    assert "org.test.late" in third


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def test_build_command_passes_known_params_and_input(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(
        system,
        ext_id="org.test.cmd",
        params=[{"name": "radius", "type": "int"}, {"name": "label", "type": "string"}],
    )
    catalog = ext_tool._discover()
    ext = catalog["org.test.cmd"]
    argv = ext_tool._build_command(ext, {"radius": 5, "label": "hi"}, Path("/tmp/in.svg"))
    # First two entries are interpreter + script
    assert argv[-1] == "/tmp/in.svg"
    assert "--radius=5" in argv
    assert "--label=hi" in argv


def test_build_command_renders_boolean_params_as_true_false(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.bool", params=[{"name": "flag", "type": "boolean"}])
    catalog = ext_tool._discover()
    ext = catalog["org.test.bool"]
    argv = ext_tool._build_command(ext, {"flag": True}, Path("/tmp/in.svg"))
    assert "--flag=true" in argv
    argv = ext_tool._build_command(ext, {"flag": False}, Path("/tmp/in.svg"))
    assert "--flag=false" in argv


def test_build_command_passes_through_unknown_params(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.passthrough")  # no params declared
    catalog = ext_tool._discover()
    ext = catalog["org.test.passthrough"]
    argv = ext_tool._build_command(ext, {"newflag": "abc"}, Path("/tmp/in.svg"))
    assert "--newflag=abc" in argv


def test_build_command_raises_when_no_script(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.scriptless", script=None)
    catalog = ext_tool._discover()
    ext = catalog["org.test.scriptless"]
    with pytest.raises(ValueError, match="has no script command"):
        ext_tool._build_command(ext, {}, Path("/tmp/in.svg"))


# ---------------------------------------------------------------------------
# Operation: list
# ---------------------------------------------------------------------------


async def test_list_returns_all_extensions(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.a")
    _write_inx(system, ext_id="org.test.b")
    res = await ext_tool.inkscape_extension(operation="list")
    assert res["success"] is True
    ids = {e["id"] for e in res["data"]["extensions"]}
    assert ids == {"org.test.a", "org.test.b"}


async def test_list_filters_by_substring(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.alpha")
    _write_inx(system, ext_id="org.test.beta")
    _write_inx(system, ext_id="org.test.gamma")
    res = await ext_tool.inkscape_extension(operation="list", target="beta")
    ids = {e["id"] for e in res["data"]["extensions"]}
    assert ids == {"org.test.beta"}


# ---------------------------------------------------------------------------
# Operation: describe
# ---------------------------------------------------------------------------


async def test_describe_returns_full_param_schema(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(
        system,
        ext_id="org.test.describe",
        params=[{"name": "x", "type": "int", "default": "1", "desc": "X coord"}],
    )
    res = await ext_tool.inkscape_extension(operation="describe", target="org.test.describe")
    assert res["success"] is True
    assert res["data"]["id"] == "org.test.describe"
    assert res["data"]["params"][0]["name"] == "x"
    assert res["data"]["params"][0]["default"] == "1"


async def test_describe_unknown_extension_fails(fake_ext_dirs):
    res = await ext_tool.inkscape_extension(operation="describe", target="org.nope.zzz")
    assert res["success"] is False
    assert "no extension with id" in res["message"]


async def test_describe_missing_target_fails(fake_ext_dirs):
    res = await ext_tool.inkscape_extension(operation="describe")
    assert res["success"] is False
    assert "target" in res["message"].lower()


# ---------------------------------------------------------------------------
# Operation: run
# ---------------------------------------------------------------------------


async def test_run_invokes_subprocess_with_args_and_writes_output(fake_ext_dirs, tmp_path):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.run", params=[{"name": "size", "type": "int"}])
    input_svg = tmp_path / "in.svg"
    input_svg.write_text("<svg/>")
    output_svg = tmp_path / "out.svg"

    async def fake_run(argv, cwd):
        assert "--size=42" in argv
        assert argv[-1] == str(input_svg)
        return True, b'<svg modified="yes"/>', ""

    with patch.object(ext_tool, "_run_subprocess", fake_run):
        res = await ext_tool.inkscape_extension(
            operation="run",
            target="org.test.run",
            params=json.dumps({"size": 42}),
            input_path=str(input_svg),
            output_path=str(output_svg),
        )

    assert res["success"] is True
    assert output_svg.read_text() == '<svg modified="yes"/>'
    assert res["data"]["bytes"] == len('<svg modified="yes"/>')


async def test_run_defaults_output_to_input_when_omitted(fake_ext_dirs, tmp_path):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.inplace")
    input_svg = tmp_path / "inplace.svg"
    input_svg.write_text("<svg/>")

    async def fake_run(argv, cwd):
        return True, b'<svg edited="1"/>', ""

    with patch.object(ext_tool, "_run_subprocess", fake_run):
        res = await ext_tool.inkscape_extension(
            operation="run",
            target="org.test.inplace",
            input_path=str(input_svg),
        )

    assert res["success"] is True
    assert input_svg.read_text() == '<svg edited="1"/>'


async def test_run_propagates_subprocess_failure(fake_ext_dirs, tmp_path):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.failrun")
    input_svg = tmp_path / "in.svg"
    input_svg.write_text("<svg/>")

    async def fake_run(argv, cwd):
        return False, b"", "Traceback: something exploded"

    with patch.object(ext_tool, "_run_subprocess", fake_run):
        res = await ext_tool.inkscape_extension(
            operation="run",
            target="org.test.failrun",
            input_path=str(input_svg),
        )

    assert res["success"] is False
    assert "exploded" in res["message"]


async def test_run_rejects_relative_input_path(fake_ext_dirs):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.relpath")
    res = await ext_tool.inkscape_extension(
        operation="run",
        target="org.test.relpath",
        input_path="relative/in.svg",
    )
    assert res["success"] is False
    assert "absolute" in res["message"]


async def test_run_rejects_missing_input(fake_ext_dirs, tmp_path):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.noinput")
    res = await ext_tool.inkscape_extension(
        operation="run",
        target="org.test.noinput",
        input_path=str(tmp_path / "does_not_exist.svg"),
    )
    assert res["success"] is False
    assert "does not exist" in res["message"]


async def test_run_rejects_invalid_params_json(fake_ext_dirs, tmp_path):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.badparams")
    input_svg = tmp_path / "in.svg"
    input_svg.write_text("<svg/>")
    res = await ext_tool.inkscape_extension(
        operation="run",
        target="org.test.badparams",
        params="not json",
        input_path=str(input_svg),
    )
    assert res["success"] is False
    assert "not valid JSON" in res["message"]


# ---------------------------------------------------------------------------
# Operation: run_live
# ---------------------------------------------------------------------------


async def test_run_live_empty_params_fires_noprefs_action(fake_ext_dirs, monkeypatch):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.live")

    bus = MagicMock()
    bus.is_available.return_value = True
    bus.list_actions.side_effect = lambda scope, *a: ["org.test.live.noprefs"] if scope == "app" else []
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    res = await ext_tool.inkscape_extension(operation="run_live", target="org.test.live")
    assert res["success"] is True
    assert res["data"]["mode"] == "noprefs"
    assert res["data"]["undo_preserved"] is True
    bus.activate.assert_called_with("org.test.live.noprefs", scope="app", window_id=1)


async def test_run_live_fails_when_bridge_unavailable(fake_ext_dirs, monkeypatch):
    bus = MagicMock()
    bus.is_available.return_value = False
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)
    res = await ext_tool.inkscape_extension(operation="run_live", target="org.test.live")
    assert res["success"] is False
    assert "bridge unavailable" in res["message"]


async def test_run_live_unknown_action_fails(fake_ext_dirs, monkeypatch):
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.notregistered")

    bus = MagicMock()
    bus.is_available.return_value = True
    bus.list_actions.return_value = []
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.notregistered",
    )
    assert res["success"] is False
    assert res["error"] == "action not registered"
    assert "no D-Bus action" in res["message"]


# ---------------------------------------------------------------------------
# Operation dispatch / argument validation
# ---------------------------------------------------------------------------


async def test_unknown_operation_fails():
    res = await ext_tool.inkscape_extension(operation="teleport")
    assert res["success"] is False
    assert "unknown operation" in res["message"]


async def test_non_object_params_json_rejected():
    res = await ext_tool.inkscape_extension(
        operation="run",
        target="anything",
        params="[1,2,3]",
        input_path="/tmp/in.svg",
    )
    assert res["success"] is False
    assert "JSON object" in res["message"]


# ---------------------------------------------------------------------------
# Output-wrapping helper (render-on-empty-canvas approach)
# ---------------------------------------------------------------------------


def test_extract_output_wraps_all_root_children_in_a_group():
    output = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><symbol id="s1"><path d="M 0 0"/></symbol></defs>'
        '<g id="formula"><use href="#s1"/></g>'
        "</svg>"
    )
    wrapper_xml = ext_tool._extract_extension_output(output, "mcp-ext-test")
    root = etree.fromstring(wrapper_xml.encode("utf-8"))
    assert root.tag == "{http://www.w3.org/2000/svg}g"
    assert root.get("id") == "mcp-ext-test"
    # All output children should be inside the wrapper.
    assert len(list(root)) == 2  # <defs> + <g>
    assert "formula" in wrapper_xml
    assert "s1" in wrapper_xml


def test_extract_output_handles_empty_canvas_output():
    """Transformer extensions run on an empty canvas produce empty output.
    The wrapper should still serialize cleanly but have zero children."""
    output = '<svg xmlns="http://www.w3.org/2000/svg"/>'
    wrapper_xml = ext_tool._extract_extension_output(output, "mcp-ext-empty")
    root = etree.fromstring(wrapper_xml.encode("utf-8"))
    assert len(list(root)) == 0


# ---------------------------------------------------------------------------
# run_live (params path → render-on-empty-canvas → single edit_xml append)
# ---------------------------------------------------------------------------


async def test_run_live_with_params_renders_and_appends(fake_ext_dirs, tmp_path, monkeypatch):
    """End-to-end run_live params path: stubs out _op_run + invoke_extension,
    verifies the empty-canvas render + single-edit_xml-append wiring."""
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.gen", params=[{"name": "x", "type": "int"}])

    bus = MagicMock()
    bus.is_available.return_value = True
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    scratch = tmp_path / "scratch.svg"

    from inkscape_mcp.tools import live as live_mod

    monkeypatch.setattr(live_mod, "_scratch_path", lambda: scratch)

    # Verify the extension was invoked with the empty canvas, then simulate
    # generator output by writing new content to the scratch path.
    async def fake_run(operation, target, params, input_path, output_path, start):
        assert Path(input_path).read_text().startswith("<?xml")
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in Path(input_path).read_text()
        Path(output_path).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><g id="formula"><path d="M 0 0 L 10 10"/></g></svg>'
        )
        return {
            "success": True,
            "operation": "run_live",
            "message": "",
            "data": {},
            "execution_time_ms": 1.0,
            "error": "",
        }

    monkeypatch.setattr(ext_tool, "_op_run", fake_run)

    # Capture what gets sent to mcp_edit_xml.
    from inkscape_mcp import extension_bridge

    captured = {}

    async def fake_invoke(bus_, action, spec, timeout_s=15.0):
        captured["action"] = action
        captured["spec"] = spec
        return extension_bridge.ExchangeResult(success=True, data={"ok": True, "affected": 1})

    monkeypatch.setattr("inkscape_mcp.extension_bridge.invoke_extension", fake_invoke)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.gen",
        params='{"x": 1}',
    )
    assert res["success"] is True, res
    assert res["data"]["mode"] == "render-and-merge"
    assert res["data"]["undo_preserved"] is True
    assert res["data"]["wrapper_id"].startswith("mcp-ext-")
    # Verify the edit_xml call shape — one append at /svg:svg with the wrapper.
    assert captured["action"] == "org.inkscape.mcp.edit-xml.noprefs"
    assert captured["spec"]["xpath"] == "/svg:svg"
    assert captured["spec"]["action"] == "append"
    assert "formula" in captured["spec"]["xml"]
    assert "mcp-ext-" in captured["spec"]["xml"]


async def test_run_live_with_params_reports_empty_output(fake_ext_dirs, tmp_path, monkeypatch):
    """Transformer extensions on an empty canvas produce no usable output —
    must fail with a hint to use the no-params path instead."""
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.transformer")

    bus = MagicMock()
    bus.is_available.return_value = True
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    scratch = tmp_path / "scratch.svg"

    from inkscape_mcp.tools import live as live_mod

    monkeypatch.setattr(live_mod, "_scratch_path", lambda: scratch)

    async def fake_run(operation, target, params, input_path, output_path, start):
        # Extension echoed the empty canvas — no new content produced.
        Path(output_path).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        return {
            "success": True,
            "operation": "run_live",
            "message": "",
            "data": {},
            "execution_time_ms": 1.0,
            "error": "",
        }

    monkeypatch.setattr(ext_tool, "_op_run", fake_run)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.transformer",
        params='{"a": 1}',
    )
    assert res["success"] is False
    assert "transformer extension" in res["message"]
    assert res["error"] == "empty output"


async def test_run_live_with_wrapper_id_reuses_id_and_pre_removes(
    fake_ext_dirs,
    tmp_path,
    monkeypatch,
):
    """When wrapper_id is supplied, the tool must:
    1. Pre-fire a remove mutation on //*[@id=<wrapper_id>] to clear any prior render
    2. Use the supplied id (not a fresh UUID) for the new wrapper
    3. Surface replaced_existing=True when the remove actually deleted something
    """
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.reuse")

    bus = MagicMock()
    bus.is_available.return_value = True
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    scratch = tmp_path / "scratch.svg"
    from inkscape_mcp.tools import live as live_mod

    monkeypatch.setattr(live_mod, "_scratch_path", lambda: scratch)

    async def fake_run(operation, target, params, input_path, output_path, start):
        Path(output_path).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><g id="formula-v2"><path d="M 1 1 L 2 2"/></g></svg>'
        )
        return {
            "success": True,
            "operation": "run_live",
            "message": "",
            "data": {},
            "execution_time_ms": 1.0,
            "error": "",
        }

    monkeypatch.setattr(ext_tool, "_op_run", fake_run)

    # Capture every invoke_extension call. First call (remove) returns ok:True
    # to simulate "a wrapper with that id was present and was removed".
    from inkscape_mcp import extension_bridge

    calls = []

    async def fake_invoke(bus_, action, spec, timeout_s=15.0):
        calls.append({"action": action, "spec": spec})
        return extension_bridge.ExchangeResult(
            success=True,
            data={"ok": True, "affected": 1},
        )

    monkeypatch.setattr("inkscape_mcp.extension_bridge.invoke_extension", fake_invoke)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.reuse",
        params='{"x": 1}',
        wrapper_id="my-formula",
    )
    assert res["success"] is True, res
    assert res["data"]["wrapper_id"] == "my-formula"
    assert res["data"]["replaced_existing"] is True
    assert "replaced existing" in res["message"]
    # Two edit_xml calls: remove + append.
    assert len(calls) == 2
    assert calls[0]["spec"]["action"] == "remove"
    assert "my-formula" in calls[0]["spec"]["xpath"]
    assert calls[1]["spec"]["action"] == "append"
    # The new wrapper carries our supplied id.
    assert 'id="my-formula"' in calls[1]["spec"]["xml"]


async def test_run_live_wrapper_id_rejects_xpath_injection(fake_ext_dirs, monkeypatch):
    """The wrapper_id is interpolated into an xpath — must validate to prevent
    injection (e.g. a quote that escapes the literal context)."""
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.validate")

    bus = MagicMock()
    bus.is_available.return_value = True
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.validate",
        params='{"x": 1}',
        wrapper_id="bad'id with quote",
    )
    assert res["success"] is False
    assert "wrapper_id" in res["message"]
    assert res["error"] == "invalid wrapper_id"


async def test_run_live_wrapper_id_first_use_does_not_report_replaced(
    fake_ext_dirs,
    tmp_path,
    monkeypatch,
):
    """If the supplied wrapper_id doesn't exist yet, replaced_existing must be
    False (remove returned ok:false 'matched no nodes' — that's fine)."""
    system, _ = fake_ext_dirs
    _write_inx(system, ext_id="org.test.first")

    bus = MagicMock()
    bus.is_available.return_value = True
    monkeypatch.setattr(ext_tool, "_get_bus", lambda: bus)

    scratch = tmp_path / "scratch.svg"
    from inkscape_mcp.tools import live as live_mod

    monkeypatch.setattr(live_mod, "_scratch_path", lambda: scratch)

    async def fake_run(operation, target, params, input_path, output_path, start):
        Path(output_path).write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="x"><path d="M 0 0"/></g></svg>')
        return {
            "success": True,
            "operation": "run_live",
            "message": "",
            "data": {},
            "execution_time_ms": 1.0,
            "error": "",
        }

    monkeypatch.setattr(ext_tool, "_op_run", fake_run)

    from inkscape_mcp import extension_bridge

    call_n = {"i": 0}

    async def fake_invoke(bus_, action, spec, timeout_s=15.0):
        call_n["i"] += 1
        if spec.get("action") == "remove":
            # Simulate "id didn't exist"
            return extension_bridge.ExchangeResult(
                success=True,
                data={"ok": False, "error": "xpath matched no nodes"},
            )
        return extension_bridge.ExchangeResult(
            success=True,
            data={"ok": True, "affected": 1},
        )

    monkeypatch.setattr("inkscape_mcp.extension_bridge.invoke_extension", fake_invoke)

    res = await ext_tool.inkscape_extension(
        operation="run_live",
        target="org.test.first",
        params='{"x": 1}',
        wrapper_id="brand-new",
    )
    assert res["success"] is True
    assert res["data"]["replaced_existing"] is False
    assert res["data"]["wrapper_id"] == "brand-new"
