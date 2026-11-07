"""Python 3.14 runs without pip inkex: inkex 1.4.1 caps lxml<6 and lxml 5.x has no 3.14
wheels, so installs on 3.14 used to fail compiling lxml (issue #36). Extensions then
import the inkex bundled with Inkscape instead."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from inkscape_mcp import platform_support
from inkscape_mcp.tools import extension

ROOT = Path(__file__).resolve().parent.parent


def test_dependencies_skip_pip_inkex_on_314():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert "inkex>=1.2.0; python_version < '3.14'" in deps
    assert "lxml>=6.0; python_version >= '3.14'" in deps


def _capture_env(monkeypatch) -> dict:
    captured: dict = {}

    async def fake_exec(*argv, **kwargs):
        captured.update(kwargs["env"])
        proc = Mock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"<svg/>", b""))
        return proc

    monkeypatch.setattr(extension.asyncio, "create_subprocess_exec", fake_exec)
    return captured


async def test_bundled_inkex_on_pythonpath_without_pip_inkex(monkeypatch, tmp_path):
    with_inkex, without = tmp_path / "with", tmp_path / "without"
    (with_inkex / "inkex").mkdir(parents=True)
    without.mkdir()
    monkeypatch.setattr(extension, "_SYSTEM_EXT_DIRS", (without, with_inkex))
    monkeypatch.setattr(extension.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setenv("PYTHONPATH", "/existing")
    env = _capture_env(monkeypatch)

    ok, _, _ = await extension._run_subprocess(["python", "ext.py"], cwd=None)

    assert ok
    assert env["PYTHONPATH"].split(extension.os.pathsep) == [str(with_inkex), "/existing"]


async def test_pythonpath_untouched_with_pip_inkex(monkeypatch, tmp_path):
    (tmp_path / "inkex").mkdir()
    monkeypatch.setattr(extension, "_SYSTEM_EXT_DIRS", (tmp_path,))
    monkeypatch.setattr(extension.importlib.util, "find_spec", lambda name: object())
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = _capture_env(monkeypatch)

    await extension._run_subprocess(["python", "ext.py"], cwd=None)

    assert "PYTHONPATH" not in env


def test_windows_extension_dirs_follow_the_inkscape_install(monkeypatch):
    monkeypatch.setattr(platform_support, "is_macos", lambda: False)
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    monkeypatch.setattr(platform_support, "resolve_inkscape_binary", lambda: None)
    monkeypatch.delenv("INKS_INKSCAPE_BIN", raising=False)
    monkeypatch.setenv("INKSCAPE_BIN", "D:/Apps/Inkscape/bin/inkscape.exe")
    monkeypatch.setenv("ProgramFiles", "C:/Program Files")

    dirs = platform_support.system_extensions_dirs()

    assert dirs == (
        Path("D:/Apps/Inkscape/share/inkscape/extensions"),
        Path("C:/Program Files/Inkscape/share/inkscape/extensions"),
    )
