"""Security policy: path scoping, action vetting, strict mode, atomic outputs, process control."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client

from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.proc_utils import terminate_process_tree
from inkscape_mcp.security import (
    SecurityError,
    SecurityPolicy,
    atomic_output,
    validate_action_chain,
)
from tests._helpers import payload as _payload

FIXTURES = Path(__file__).parent / "fixtures"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups / symlinks")


def _policy(tmp_path, **kw) -> SecurityPolicy:
    return SecurityPolicy(allowed_dirs=(tmp_path.resolve(),), **kw)


# --------------------------------------------------------------------------- path scoping


def test_unrestricted_policy_allows_any_path(tmp_path):
    p = SecurityPolicy()
    assert p.resolve_path(str(tmp_path / "x.svg")) == (tmp_path / "x.svg").resolve()


def test_path_inside_scope_is_allowed(tmp_path):
    f = tmp_path / "a.svg"
    f.write_text("<svg/>")
    assert _policy(tmp_path).resolve_path(str(f)) == f.resolve()


def test_relative_path_is_anchored_in_the_first_allowed_dir(tmp_path):
    assert _policy(tmp_path).resolve_path("sub/a.svg", role="output") == (tmp_path / "sub/a.svg").resolve()


@pytest.mark.parametrize("bad", ["../escape.svg", "sub/../../escape.svg", "/etc/passwd", "~/x.svg"])
def test_paths_outside_scope_are_refused(tmp_path, bad):
    with pytest.raises(SecurityError, match="outside the allowed directories"):
        _policy(tmp_path).resolve_path(bad)


def test_sibling_dir_with_a_shared_prefix_is_not_inside(tmp_path):
    """/ws vs /ws-evil: a startswith() check would wrongly allow it."""
    ws = tmp_path / "ws"
    ws.mkdir()
    evil = tmp_path / "ws-evil"
    evil.mkdir()
    with pytest.raises(SecurityError):
        SecurityPolicy(allowed_dirs=(ws.resolve(),)).resolve_path(str(evil / "a.svg"))


@posix_only
def test_symlink_pointing_out_of_scope_is_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    secret = tmp_path / "secret.svg"
    secret.write_text("<svg/>")
    (ws / "link.svg").symlink_to(secret)
    with pytest.raises(SecurityError):
        SecurityPolicy(allowed_dirs=(ws.resolve(),)).resolve_path(str(ws / "link.svg"))


@posix_only
def test_output_through_a_symlinked_directory_is_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "d").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecurityError):
        SecurityPolicy(allowed_dirs=(ws.resolve(),)).resolve_path(str(ws / "d" / "o.svg"), role="output")


def test_nul_byte_is_refused(tmp_path):
    with pytest.raises(SecurityError, match="NUL"):
        SecurityPolicy().resolve_path("a\0b.svg")


def test_oversized_input_is_refused(tmp_path):
    f = tmp_path / "big.svg"
    f.write_bytes(b"x" * 2048)
    with pytest.raises(SecurityError, match="exceeds"):
        SecurityPolicy(max_file_bytes=1024).resolve_path(str(f))
    # Outputs don't exist yet, and the limit is about reading hostile inputs.
    SecurityPolicy(max_file_bytes=1024).resolve_path(str(f), role="output")


# --------------------------------------------------------------------------- policy construction


def test_from_config_reads_dirs_and_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("INKSCAPE_MCP_ALLOWED_DIRS", raising=False)
    monkeypatch.delenv("INKSCAPE_MCP_SECURITY", raising=False)
    cfg = SimpleNamespace(allowed_directories=[str(tmp_path)], security_mode="permissive", max_file_size_mb=5)
    p = SecurityPolicy.from_config(cfg)
    assert p.allowed_dirs == (tmp_path.resolve(),)
    assert p.max_file_bytes == 5 * 1024 * 1024
    assert p.strict is False and p.restricted is True


def test_env_overrides_config(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("INKSCAPE_MCP_ALLOWED_DIRS", str(other))
    monkeypatch.setenv("INKSCAPE_MCP_SECURITY", "strict")
    cfg = SimpleNamespace(allowed_directories=[str(tmp_path)], security_mode="permissive", max_file_size_mb=5)
    p = SecurityPolicy.from_config(cfg)
    assert p.allowed_dirs == (other.resolve(),)
    assert p.strict is True


def test_strict_without_dirs_scopes_to_cwd_instead_of_everywhere(monkeypatch):
    monkeypatch.delenv("INKSCAPE_MCP_ALLOWED_DIRS", raising=False)
    monkeypatch.setenv("INKSCAPE_MCP_SECURITY", "strict")
    p = SecurityPolicy.from_config(SimpleNamespace(allowed_directories=[], max_file_size_mb=5))
    assert p.restricted and p.allowed_dirs == (Path.cwd().resolve(),)


def test_invalid_mode_falls_back_to_permissive(monkeypatch):
    monkeypatch.setenv("INKSCAPE_MCP_SECURITY", "paranoid")
    monkeypatch.delenv("INKSCAPE_MCP_ALLOWED_DIRS", raising=False)
    assert SecurityPolicy.from_config(SimpleNamespace(allowed_directories=[], max_file_size_mb=5)).strict is False


# --------------------------------------------------------------------------- action vetting


@pytest.mark.parametrize(
    "action",
    ["select-by-id:a;file-open:/etc/hosts", "select-all\nfile-close", "a\rb", "x\0y", "bad name", "", ":nameless"],
)
def test_unsafe_actions_are_rejected(action):
    with pytest.raises(SecurityError):
        validate_action_chain([action])


@pytest.mark.parametrize(
    "action", ["select-all", "select-by-id:rect1", "export-dpi:300", "object-set-attribute:fill,red"]
)
def test_ordinary_actions_pass(action):
    validate_action_chain([action])


def test_non_string_action_is_rejected():
    with pytest.raises(SecurityError):
        validate_action_chain([123])  # type: ignore[list-item]


def test_strict_allowlist():
    p = SecurityPolicy(strict=True)
    for ok in ("select-all", "path-union", "transform-rotate:45", "object-to-path", "query-all"):
        p.check_raw_action(ok)
    for bad in (
        "file-open:/x",
        "export-filename:/tmp/x",
        "window-close",
        "org.inkscape.mcp.execute",
        "extension",
        "nonsense",
    ):
        with pytest.raises(SecurityError):
            p.check_raw_action(bad)


def test_permissive_does_not_apply_the_allowlist():
    SecurityPolicy().check_raw_action("file-open:/x")  # chain-safe, so fine outside strict mode


def test_strict_blocks_execute_inkex_and_non_stock_extensions():
    p = SecurityPolicy(strict=True)
    with pytest.raises(SecurityError):
        p.vet_call("inkscape_live", {"operation": "execute_inkex", "payload": "print(1)"})
    with pytest.raises(SecurityError):
        p.vet_call("inkscape_extension", {"operation": "run", "target": "com.evil.thing"})
    p.vet_call("inkscape_extension", {"operation": "run", "target": "org.inkscape.color.negative"})
    # Permissive mode keeps today's behaviour.
    SecurityPolicy().vet_call("inkscape_live", {"operation": "execute_inkex", "payload": "x"})


def test_vet_call_rewrites_every_path_argument(tmp_path):
    (tmp_path / "in.svg").write_text("<svg/>")
    out = _policy(tmp_path).vet_call(
        "inkscape_file",
        {"operation": "convert", "input_path": "in.svg", "output_path": "o/out.png", "input_paths": ["in.svg"]},
    )
    assert out["input_path"] == str((tmp_path / "in.svg").resolve())
    assert out["output_path"] == str((tmp_path / "o/out.png").resolve())
    assert out["input_paths"] == [str((tmp_path / "in.svg").resolve())]


def test_vet_call_checks_every_path_in_a_list(tmp_path):
    with pytest.raises(SecurityError):
        _policy(tmp_path).vet_call(
            "inkscape_file", {"operation": "batch_convert", "input_paths": ["a.svg", "/etc/passwd"]}
        )


def test_unrestricted_mode_passes_arguments_through_untouched():
    """No scope configured: relative paths must stay relative so each tool's own rules still apply."""
    args = {"operation": "convert", "input_path": "rel/in.svg", "output_path": "out.png", "input_paths": ["a.svg"]}
    assert SecurityPolicy().vet_call("inkscape_file", args) == args
    live = {"operation": "open_file", "target": "relative/path.svg"}
    assert SecurityPolicy().vet_call("inkscape_live", live) == live


def test_unrestricted_mode_still_runs_the_checks(tmp_path):
    big = tmp_path / "big.svg"
    big.write_bytes(b"x" * 2048)
    with pytest.raises(SecurityError):
        SecurityPolicy(max_file_bytes=1024).vet_call("inkscape_file", {"operation": "info", "input_path": str(big)})
    with pytest.raises(SecurityError):
        SecurityPolicy().vet_call("inkscape_file", {"operation": "info", "input_path": "a\0b"})


def test_live_open_file_target_is_a_path_but_other_targets_are_not(tmp_path):
    p = _policy(tmp_path)
    with pytest.raises(SecurityError):
        p.vet_call("inkscape_live", {"operation": "open_file", "target": "/etc/passwd"})
    # A selector / action name must be left alone.
    assert p.vet_call("inkscape_live", {"operation": "set_selection", "target": "#rect1"})["target"] == "#rect1"


def test_rasterize_filename_inside_payload_json_is_vetted(tmp_path):
    p = _policy(tmp_path)
    ok = p.vet_call(
        "inkscape_live", {"operation": "rasterize", "payload": f'{{"filename": "{tmp_path}/r.png", "dpi": 96}}'}
    )
    assert '"dpi": 96' in ok["payload"]
    with pytest.raises(SecurityError):
        p.vet_call("inkscape_live", {"operation": "rasterize", "payload": '{"filename": "/etc/cron.d/x.png"}'})


def test_extension_params_paths_are_vetted(tmp_path):
    p = _policy(tmp_path)
    with pytest.raises(SecurityError):
        p.vet_call(
            "inkscape_extension", {"operation": "run", "target": "org.inkscape.x", "params": '{"filename": "/etc/x"}'}
        )
    with pytest.raises(SecurityError):
        p.vet_call(
            "inkscape_system",
            {
                "operation": "execute_extension",
                "extension_id": "org.inkscape.x",
                "extension_params": {"nested": {"output_dir": "../../x"}},
            },
        )
    # Non-path values and ordinary params pass untouched.
    out = p.vet_call(
        "inkscape_extension", {"operation": "run", "target": "org.inkscape.x", "params": '{"angle": 45, "text": "a/b"}'}
    )
    assert '"angle": 45' in out["params"] and '"a/b"' in out["params"]


def test_other_payloads_are_not_treated_as_paths(tmp_path):
    svg = '<svg><image href="/etc/hosts"/></svg>'  # content, not a path argument
    assert _policy(tmp_path).vet_call("inkscape_live", {"operation": "insert_svg", "payload": svg})["payload"] == svg


def test_system_tool_extension_id_respects_strict_mode():
    with pytest.raises(SecurityError):
        SecurityPolicy(strict=True).vet_call("inkscape_system", {"operation": "status", "extension_id": "com.evil.x"})


# --------------------------------------------------------------------------- atomic outputs


def test_atomic_output_moves_into_place_on_success(tmp_path):
    final = tmp_path / "o.svg"
    with atomic_output(final) as tmp:
        assert tmp.suffix == ".svg" and tmp != final  # suffix kept: Inkscape picks the format from it
        tmp.write_text("<svg/>")
    assert final.read_text() == "<svg/>"
    assert [p.name for p in tmp_path.iterdir()] == ["o.svg"]


def test_atomic_output_failure_leaves_existing_file_untouched_and_no_debris(tmp_path):
    final = tmp_path / "o.svg"
    final.write_text("ORIGINAL")
    with pytest.raises(RuntimeError), atomic_output(final) as tmp:
        tmp.write_text("PARTIAL")
        raise RuntimeError("inkscape crashed")
    assert final.read_text() == "ORIGINAL"
    assert [p.name for p in tmp_path.iterdir()] == ["o.svg"]


def test_atomic_output_rejects_an_empty_result(tmp_path):
    final = tmp_path / "o.svg"
    with pytest.raises(FileNotFoundError), atomic_output(final) as tmp:
        tmp.write_text("")
    assert not final.exists()


async def test_failed_export_does_not_clobber_an_existing_output(server, tmp_path, monkeypatch):
    out = tmp_path / "keep.svg"
    out.write_text("PRECIOUS")

    async def crash(cmd_args, timeout):
        target = next(a.split("=", 1)[1] for a in cmd_args if a.startswith("--export-filename="))
        Path(target).write_text("<svg><!-- half")  # partial write, then die
        raise RuntimeError("segfault")

    monkeypatch.setattr(server.cli_wrapper, "_execute_command_capture", crash)
    with pytest.raises(RuntimeError):
        await server.cli_wrapper._execute_actions(str(FIXTURES / "minimal.svg"), ["select-all"], str(out))
    assert out.read_text() == "PRECIOUS"
    assert [p.name for p in tmp_path.iterdir()] == ["keep.svg"]


async def test_chain_export_filename_is_staged_too(server, tmp_path, monkeypatch):
    """Most tools put export-filename inside the chain; that is what must be redirected."""
    out = tmp_path / "chain.svg"
    seen = {}

    async def fake(cmd_args, timeout):
        chain = next(a for a in cmd_args if a.startswith("--actions="))
        staged = next(x for x in chain.removeprefix("--actions=").split(";") if x.startswith("export-filename:"))
        seen["staged"] = staged.split(":", 1)[1]
        Path(seen["staged"]).write_text("<svg/>")
        return "", ""

    monkeypatch.setattr(server.cli_wrapper, "_execute_command_capture", fake)
    await server.cli_wrapper._execute_actions(
        str(FIXTURES / "minimal.svg"), ["select-all", f"export-filename:{out}", "export-do"], None
    )
    assert seen["staged"] != str(out) and Path(seen["staged"]).suffix == ".svg"
    assert out.read_text() == "<svg/>"


async def test_cli_wrapper_refuses_an_injected_chain(server, tmp_path):
    from inkscape_mcp.cli_wrapper import InkscapeExecutionError

    with pytest.raises(InkscapeExecutionError, match="unsafe action chain"):
        await server.cli_wrapper._execute_actions(
            str(FIXTURES / "minimal.svg"), ["select-by-id:a;file-open:/etc/hosts"], str(tmp_path / "o.svg")
        )
    assert not (tmp_path / "o.svg").exists()


# --------------------------------------------------------------------------- process control


@posix_only
async def test_timeout_kills_the_whole_process_tree(tmp_path):
    """A parent that spawned a child must not leave the child running after a timeout."""
    pidfile = tmp_path / "child.pid"
    script = f"sleep 60 & echo $! > {pidfile}; wait"
    proc = await asyncio.create_subprocess_exec("sh", "-c", script, start_new_session=True)
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.05)
    child = int(pidfile.read_text())
    await terminate_process_tree(proc)
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


async def test_process_slots_cap_concurrency(server, monkeypatch):
    wrapper = server.cli_wrapper
    monkeypatch.setattr(wrapper.config, "max_concurrent_processes", 2, raising=False)
    wrapper._process_slots = None
    running = peak = 0

    async def fake_run(cmd_args, timeout):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return "", ""

    monkeypatch.setattr(wrapper, "_run_one", fake_run)
    await asyncio.gather(*(wrapper._execute_command_capture(["x"], 5) for _ in range(8)))
    assert peak == 2


# --------------------------------------------------------------------------- end to end


@pytest.fixture
async def scoped(tmp_path, monkeypatch):
    """A real server whose tools may only touch tmp_path/ws."""
    ws = tmp_path / "ws"
    ws.mkdir()
    shutil.copy(FIXTURES / "minimal.svg", ws / "minimal.svg")
    monkeypatch.setenv("INKSCAPE_MCP_ALLOWED_DIRS", str(ws))
    monkeypatch.delenv("INKSCAPE_MCP_SECURITY", raising=False)
    s = InkscapeMCPServer()
    assert await s.initialize()
    async with Client(s.mcp) as c:
        yield c, ws, tmp_path


async def test_e2e_inside_scope_works_with_relative_path(scoped):
    c, _ws, _ = scoped
    p = _payload(await c.call_tool("inkscape_file", {"operation": "info", "input_path": "minimal.svg"}))
    assert p["success"] is True, p


@pytest.mark.parametrize("bad", ["../minimal.svg", "/etc/hosts"])
async def test_e2e_input_outside_scope_is_blocked(scoped, bad):
    c, _, _ = scoped
    p = _payload(await c.call_tool("inkscape_file", {"operation": "info", "input_path": bad}))
    assert p["success"] is False and p["error"] == "security policy"
    assert "allowed directories" in p["message"]


async def test_e2e_output_outside_scope_is_blocked_and_nothing_is_written(scoped):
    c, ws, tmp = scoped
    out = tmp / "stolen.png"
    p = _payload(
        await c.call_tool(
            "inkscape_file",
            {"operation": "convert", "input_path": str(ws / "minimal.svg"), "output_path": str(out), "format": "png"},
        )
    )
    assert p["success"] is False and p["error"] == "security policy"
    assert not out.exists()


@posix_only
async def test_e2e_symlink_escape_is_blocked(scoped):
    c, ws, tmp = scoped
    (ws / "sneaky.svg").symlink_to(tmp / "ws" / ".." / "outside.svg")
    (tmp / "outside.svg").write_text("<svg/>")
    p = _payload(await c.call_tool("inkscape_file", {"operation": "info", "input_path": str(ws / "sneaky.svg")}))
    assert p["success"] is False and p["error"] == "security policy"


async def test_e2e_batch_list_is_checked_per_item(scoped):
    c, ws, _ = scoped
    p = _payload(
        await c.call_tool(
            "inkscape_file",
            {
                "operation": "batch_convert",
                "input_paths": [str(ws / "minimal.svg"), "/etc/hosts"],
                "output_dir": str(ws / "out"),
                "format": "png",
            },
        )
    )
    assert p["success"] is False and p["error"] == "security policy"


async def test_e2e_in_scope_conversion_still_works(scoped):
    c, ws, _ = scoped
    p = _payload(
        await c.call_tool(
            "inkscape_file",
            {
                "operation": "convert",
                "input_path": "minimal.svg",
                "output_path": "out/minimal.png",
                "format": "png",
            },
        )
    )
    assert p["success"] is True, p
    assert (ws / "out" / "minimal.png").stat().st_size > 0
    assert not list((ws / "out").glob("*.tmp-*"))


async def test_e2e_strict_mode_blocks_execute_inkex_before_touching_inkscape(tmp_path, monkeypatch):
    monkeypatch.setenv("INKSCAPE_MCP_ALLOWED_DIRS", str(tmp_path))
    monkeypatch.setenv("INKSCAPE_MCP_SECURITY", "strict")
    s = InkscapeMCPServer()
    assert await s.initialize()
    async with Client(s.mcp) as c:
        p = _payload(await c.call_tool("inkscape_live", {"operation": "execute_inkex", "payload": "import os"}))
        assert p["success"] is False and p["error"] == "security policy"
        assert "strict" in p["message"]
        p = _payload(
            await c.call_tool("inkscape_live", {"operation": "apply_action", "target": "file-open:/etc/hosts"})
        )
        assert p["success"] is False and p["error"] == "security policy"
