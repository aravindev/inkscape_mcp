"""Python must not write __pycache__ into the Inkscape install.

Extensions and the bundled inkex live inside Inkscape.app on macOS. When the MCP's
Python (headless `inkscape_extension run`, or the managed instance's python-interpreter
preference) imported them, it wrote cpython-3xx .pyc files next to the sources and broke
the app's code-signature seal. Every process that can run extension code must carry
PYTHONPYCACHEPREFIX pointing at the MCP's cache.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from inkscape_mcp import bus_manager, platform_support
from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.tools import extension, live


@pytest.fixture(autouse=True)
def _clean_bytecode_env(monkeypatch):
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)


def _expected() -> str:
    return str(platform_support.pycache_dir())


def test_subprocess_env_sets_cache_prefix():
    env = platform_support.subprocess_env({"PATH": "/bin"})
    assert env == {"PATH": "/bin", "PYTHONPYCACHEPREFIX": _expected()}


@pytest.mark.parametrize(
    "preset",
    [{"PYTHONPYCACHEPREFIX": "/mine"}, {"PYTHONDONTWRITEBYTECODE": "1"}],
)
def test_subprocess_env_respects_caller_choice(preset):
    env = platform_support.subprocess_env(dict(preset))
    assert env == preset


def test_subprocess_env_does_not_mutate_os_environ():
    platform_support.subprocess_env()
    assert "PYTHONPYCACHEPREFIX" not in platform_support.os.environ


async def test_headless_extension_run_carries_prefix(monkeypatch):
    captured: dict = {}

    async def fake_exec(*argv, **kwargs):
        captured.update(kwargs["env"])
        proc = Mock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"<svg/>", b""))
        return proc

    monkeypatch.setattr(extension.asyncio, "create_subprocess_exec", fake_exec)
    await extension._run_subprocess(["python", "ext.py"], cwd=None)
    assert captured["PYTHONPYCACHEPREFIX"] == _expected()


def test_cli_wrapper_env_carries_prefix():
    wrapper = InkscapeCliWrapper.__new__(InkscapeCliWrapper)
    assert wrapper._get_environment()["PYTHONPYCACHEPREFIX"] == _expected()


def test_managed_inkscape_launch_carries_prefix(monkeypatch, tmp_path):
    exe = tmp_path / "inkscape"
    exe.write_text("")
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured.update(kwargs["env"])
        return Mock(pid=12345)

    monkeypatch.setattr(bus_manager, "_inkscape_registered", lambda *a: False)
    monkeypatch.setattr(bus_manager, "_launched_pid", lambda: None)
    monkeypatch.setattr(bus_manager, "_wait_registered", lambda *a: True)
    monkeypatch.setattr(bus_manager, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bus_manager, "PID_FILE", tmp_path / "inkscape.pid")
    monkeypatch.setattr(bus_manager, "default_canvas", lambda: str(tmp_path / "canvas.svg"))
    monkeypatch.setattr(bus_manager.platform_support, "set_inkscape_python_preference", lambda *a: {})
    monkeypatch.setattr(bus_manager.subprocess, "Popen", fake_popen)

    assert bus_manager.ensure_inkscape(None, "unix:path=/x", str(exe))
    assert captured["PYTHONPYCACHEPREFIX"] == _expected()
    assert captured["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/x"


def test_action_list_probe_carries_prefix(monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(live, "_ACTION_DESCRIPTIONS", None)
    monkeypatch.setattr(subprocess, "run", fake_run)
    live._load_action_descriptions("inkscape")
    assert captured["PYTHONPYCACHEPREFIX"] == _expected()


def test_prefix_keeps_bytecode_out_of_source_tree(tmp_path):
    """End to end: a real interpreter honours the env and leaves the source dir clean."""
    src = tmp_path / "bundle"
    src.mkdir()
    (src / "mod.py").write_text("X = 1\n")
    cache = tmp_path / "cache"
    env = platform_support.subprocess_env({"PYTHONPYCACHEPREFIX": str(cache)})
    subprocess.run([sys.executable, "-c", "import mod"], cwd=src, env=env, check=True)
    assert not (src / "__pycache__").exists()
    assert any(cache.rglob("mod.*.pyc"))
