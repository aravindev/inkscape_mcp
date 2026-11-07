"""Mocked launcher regressions; run with --noconftest to avoid Inkscape startup."""

from __future__ import annotations

import ctypes
import errno
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inkscape_mcp import bus_manager as bm
from inkscape_mcp import platform_support


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("pid", [None, "123", True, 0, -1, 1.5, 2**64])
def test_invalid_pid_never_queries_os(monkeypatch, windows, pid):
    monkeypatch.setattr(bm, "is_windows", lambda: windows)
    kill = Mock(side_effect=AssertionError("unexpected signal"))
    native = Mock(side_effect=AssertionError("unexpected process query"))
    monkeypatch.setattr(bm.os, "kill", kill)
    monkeypatch.setattr(bm, "_windows_pid_alive", native)
    assert not bm._pid_alive(pid)
    kill.assert_not_called()
    native.assert_not_called()


@pytest.mark.parametrize(
    ("error", "alive"),
    [
        (None, True),
        (PermissionError(errno.EPERM, "denied"), True),
        (ProcessLookupError(errno.ESRCH, "gone"), False),
        (OverflowError(), False),
        (ValueError(), False),
    ],
)
def test_posix_liveness(monkeypatch, error, alive):
    monkeypatch.setattr(bm, "is_windows", lambda: False)
    kill = Mock(side_effect=error)
    monkeypatch.setattr(bm.os, "kill", kill)
    assert bm._pid_alive(123) is alive
    kill.assert_called_once_with(123, 0)


@pytest.mark.parametrize(("actual", "alive"), [("/apps/inkscape", True), ("/apps/unrelated", False), (None, True)])
def test_posix_identity(monkeypatch, actual, alive):
    monkeypatch.setattr(bm, "is_windows", lambda: False)
    monkeypatch.setattr(bm.os, "kill", Mock())
    query = Mock(return_value=actual)
    monkeypatch.setattr(bm, "_posix_process_executable", query)
    assert bm._pid_alive(123, "/apps/inkscape") is alive
    query.assert_called_once_with(123)


def test_linux_identity_query(monkeypatch):
    monkeypatch.setattr(bm, "is_macos", lambda: False)
    readlink = Mock(return_value="/apps/inkscape")
    monkeypatch.setattr(bm.os, "readlink", readlink)
    assert bm._posix_process_executable(123) == "/apps/inkscape"
    readlink.assert_called_once_with("/proc/123/exe")
    readlink.side_effect = PermissionError()
    assert bm._posix_process_executable(123) is None


@pytest.mark.parametrize("available", [True, False])
def test_macos_identity_query(monkeypatch, available):
    monkeypatch.setattr(bm, "is_macos", lambda: True)

    def proc_pidpath(pid, buffer, size):
        assert pid == 123
        assert size == 4096
        buffer.value = b"/Applications/Inkscape.app/Contents/MacOS/inkscape"
        return len(buffer.value) if available else 0

    query = Mock(side_effect=proc_pidpath)
    loader = Mock(return_value=SimpleNamespace(proc_pidpath=query))
    monkeypatch.setattr(ctypes, "CDLL", loader)
    result = bm._posix_process_executable(123)
    assert result == ("/Applications/Inkscape.app/Contents/MacOS/inkscape" if available else None)
    loader.assert_called_once_with("/usr/lib/libproc.dylib", use_errno=True)


@pytest.fixture
def windows_api(monkeypatch):
    from ctypes import wintypes

    monkeypatch.setattr(bm, "is_windows", lambda: True)
    monkeypatch.setattr(bm.os, "kill", Mock(side_effect=AssertionError("Windows must never signal")))

    def exit_code(handle, output):
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = 259
        return True

    def query_image(handle, flags, output, size):
        output.value = r"C:\Apps\Inkscape.exe"
        return True

    api = SimpleNamespace(
        OpenProcess=Mock(return_value=987),
        GetExitCodeProcess=Mock(side_effect=exit_code),
        QueryFullProcessImageNameW=Mock(side_effect=query_image),
        CloseHandle=Mock(),
    )
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=api), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", Mock(return_value=87), raising=False)
    return api


def test_windows_live_process_and_identity(windows_api):
    assert bm._pid_alive(123, r"c:\apps\inkscape.exe")
    windows_api.OpenProcess.assert_called_once_with(0x1000, False, 123)
    windows_api.CloseHandle.assert_called_once_with(987)
    assert windows_api.OpenProcess.restype is ctypes.wintypes.HANDLE


def test_windows_reused_pid(windows_api):
    assert not bm._pid_alive(123, r"C:\Apps\other.exe")
    windows_api.CloseHandle.assert_called_once_with(987)


def test_windows_exited_process(windows_api):
    def exited(handle, output):
        ctypes.cast(output, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = 0
        return True

    windows_api.GetExitCodeProcess.side_effect = exited
    assert not bm._pid_alive(123, r"C:\Apps\Inkscape.exe")
    windows_api.QueryFullProcessImageNameW.assert_not_called()
    windows_api.CloseHandle.assert_called_once_with(987)


@pytest.mark.parametrize(("error", "alive"), [(5, True), (87, False)])
def test_windows_open_failure(monkeypatch, windows_api, error, alive):
    windows_api.OpenProcess.return_value = None
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error)
    assert bm._pid_alive(123) is alive
    windows_api.CloseHandle.assert_not_called()


@pytest.mark.parametrize("failed_query", ["GetExitCodeProcess", "QueryFullProcessImageNameW"])
def test_windows_unknown_query_preserves_guard(windows_api, failed_query):
    query = getattr(windows_api, failed_query)
    query.side_effect = None
    query.return_value = False
    assert bm._pid_alive(123, r"C:\Apps\Inkscape.exe")
    windows_api.CloseHandle.assert_called_once_with(987)


def test_windows_handle_closed_on_exception(windows_api):
    windows_api.QueryFullProcessImageNameW.side_effect = OSError("query failed")
    with pytest.raises(OSError, match="query failed"):
        bm._pid_alive(123, r"C:\Apps\Inkscape.exe")
    windows_api.CloseHandle.assert_called_once_with(987)


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    executable = tmp_path / "inkscape"
    executable.touch()
    monkeypatch.setattr(bm, "is_macos", lambda: False)
    monkeypatch.setattr(bm, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bm, "PID_FILE", tmp_path / "inkscape.pid")
    monkeypatch.setattr(bm, "_inkscape_registered", Mock(return_value=False))
    monkeypatch.setattr(bm, "_wait_registered", Mock(return_value=True))
    popen = Mock(return_value=SimpleNamespace(pid=456))
    monkeypatch.setattr(bm.subprocess, "Popen", popen)
    return str(executable), popen


@pytest.mark.parametrize("lang", [None, "", "de_DE.UTF-8"])
@pytest.mark.parametrize("lc_all", [None, "", "fr_FR.UTF-8"])
def test_launcher_preserves_locale(monkeypatch, launcher, lang, lc_all):
    executable, popen = launcher
    for key, value in [("LANG", lang), ("LC_ALL", lc_all), ("LC_NUMERIC", "de_DE.UTF-8")]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    original = dict(bm.os.environ)
    assert bm.ensure_inkscape("gdbus", "test-address", executable, "drawing.svg")
    env = popen.call_args.kwargs["env"]
    assert env["LANG"] == (lang or "C.UTF-8")
    if lc_all is None:
        assert "LC_ALL" not in env
    else:
        assert env["LC_ALL"] == lc_all
    assert env["LC_NUMERIC"] == "de_DE.UTF-8"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "test-address"
    assert dict(bm.os.environ) == original


@pytest.mark.parametrize("alive", [True, False])
def test_launcher_checks_cached_process_identity(monkeypatch, launcher, alive):
    executable, popen = launcher
    bm.PID_FILE.write_text("123", encoding="utf-8")
    check = Mock(return_value=alive)
    monkeypatch.setattr(bm, "_pid_alive", check)
    assert bm.ensure_inkscape("gdbus", "test-address", executable, "drawing.svg")
    check.assert_called_once_with(123, executable)
    assert popen.call_count == (0 if alive else 1)


@pytest.mark.parametrize("text", ["not a pid", "", "12.5"])
def test_malformed_pid_file(launcher, text):
    bm.PID_FILE.write_text(text, encoding="utf-8")
    assert bm._launched_pid() is None


def test_platform_predicates_are_shared():
    assert bm.is_macos is platform_support.is_macos
    assert bm.is_windows is platform_support.is_windows


def test_macos_auth_mechanisms_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bm, "MACOS_BUS_DIR", tmp_path / "bus")
    monkeypatch.setattr(bm, "MACOS_BUS_CONFIG", tmp_path / "dbus-session.conf")
    config = bm._write_macos_bus_config().read_text(encoding="utf-8")
    assert "<auth>EXTERNAL</auth>" in config
    assert "<auth>DBUS_COOKIE_SHA1</auth>" in config


@pytest.mark.parametrize(
    ("soft", "expected"),
    [(1_048_576, 4096), (-1, 4096), (256, None), (4096, None)],
)
def test_open_file_limit_capped_for_macos_launch(monkeypatch, soft, expected):
    resource = pytest.importorskip("resource")
    if soft == -1:
        soft = resource.RLIM_INFINITY
    monkeypatch.setattr(resource, "getrlimit", lambda _: (soft, resource.RLIM_INFINITY))
    setrlimit = Mock()
    monkeypatch.setattr(resource, "setrlimit", setrlimit)
    bm._cap_open_files()
    if expected is None:
        setrlimit.assert_not_called()
    else:
        setrlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (expected, resource.RLIM_INFINITY))


def test_macos_launch_caps_open_files(monkeypatch, launcher):
    executable, popen = launcher
    monkeypatch.setattr(bm, "is_macos", lambda: True)
    monkeypatch.setattr(platform_support, "set_inkscape_python_preference", Mock())
    assert bm.ensure_inkscape("gdbus", "test-address", executable, "drawing.svg")
    assert popen.call_args.kwargs["preexec_fn"] is bm._cap_open_files
