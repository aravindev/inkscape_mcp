"""Unit tests for extension_bridge — the inkex extension transport."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from inkscape_mcp import extension_bridge as bridge


@pytest.fixture
def tmp_exchange(monkeypatch, tmp_path):
    """Redirect EXCHANGE_DIR and INSTALL_DIR to tmp_path-scoped paths."""
    ex = tmp_path / "exchange"
    inst = tmp_path / "install"
    monkeypatch.setattr(bridge, "EXCHANGE_DIR", ex)
    monkeypatch.setattr(bridge, "INSTALL_DIR", inst)
    monkeypatch.setattr(bridge, "VERSION_FILE", inst / "VERSION")
    return ex, inst


async def test_invoke_writes_input_fires_action_and_returns_result(tmp_exchange):
    ex, _ = tmp_exchange
    bus = MagicMock()

    # Simulate the extension writing result.json the moment the action fires.
    def fake_activate(action, scope="app", window_id=1):
        ex.mkdir(parents=True, exist_ok=True)
        (ex / "result.json").write_text(json.dumps({"ok": True, "echoed": {"k": "v"}}))

    bus.activate.side_effect = fake_activate

    result = await bridge.invoke_extension(bus, "org.inkscape.mcp.echo.noprefs", {"k": "v"})

    assert result.success is True
    assert result.data == {"ok": True, "echoed": {"k": "v"}}
    bus.activate.assert_called_once_with("org.inkscape.mcp.echo.noprefs", scope="app", window_id=1)
    assert json.loads((ex / "input.json").read_text()) == {"k": "v"}


async def test_invoke_times_out_when_no_result(tmp_exchange):
    bus = MagicMock()  # activate does nothing — no result.json appears.
    result = await bridge.invoke_extension(bus, "x.action", {}, timeout_s=0.15)
    assert result.success is False
    assert "did not produce result" in result.error


async def test_invoke_captures_stderr_on_timeout(tmp_exchange):
    ex, _ = tmp_exchange
    bus = MagicMock()

    # Simulate an extension that crashes — writes stderr but no result.json.
    def fake_activate(*a, **kw):
        ex.mkdir(parents=True, exist_ok=True)
        (ex / "stderr.txt").write_text("traceback line 1\ntraceback line 2\n")

    bus.activate.side_effect = fake_activate

    result = await bridge.invoke_extension(bus, "x.action", {}, timeout_s=0.15)
    assert result.success is False
    assert "traceback line 1" in result.stderr


async def test_invoke_rejects_non_object_result(tmp_exchange):
    ex, _ = tmp_exchange
    bus = MagicMock()

    def fake_activate(*a, **kw):
        ex.mkdir(parents=True, exist_ok=True)
        (ex / "result.json").write_text(json.dumps(["not", "an", "object"]))

    bus.activate.side_effect = fake_activate

    result = await bridge.invoke_extension(bus, "x.action", {})
    assert result.success is False
    assert "JSON object" in result.error


async def test_invoke_handles_malformed_result_json(tmp_exchange):
    ex, _ = tmp_exchange
    bus = MagicMock()

    def fake_activate(*a, **kw):
        ex.mkdir(parents=True, exist_ok=True)
        (ex / "result.json").write_text("not json")

    bus.activate.side_effect = fake_activate

    result = await bridge.invoke_extension(bus, "x.action", {})
    assert result.success is False
    assert "JSON" in result.error


async def test_invoke_propagates_dbus_failure(tmp_exchange):
    bus = MagicMock()
    bus.activate.side_effect = RuntimeError("bus down")
    result = await bridge.invoke_extension(bus, "x.action", {})
    assert result.success is False
    assert "bus down" in result.error


async def test_invoke_cleans_stale_result(tmp_exchange):
    """A leftover result.json from a previous call must not satisfy the wait."""
    ex, _ = tmp_exchange
    ex.mkdir(parents=True, exist_ok=True)
    (ex / "result.json").write_text(json.dumps({"stale": True}))
    bus = MagicMock()  # activate doesn't repopulate
    result = await bridge.invoke_extension(bus, "x.action", {}, timeout_s=0.15)
    assert result.success is False
    assert "did not produce result" in result.error


def test_is_installed_false_when_version_missing(tmp_exchange):
    assert bridge.is_installed() is False


def test_install_writes_version_and_copies_files(tmp_exchange):
    _, inst = tmp_exchange
    result = bridge.install_plugins()
    assert result["installed"] is True
    assert result["action"] == "copied"
    assert (inst / "VERSION").read_text().strip() == bridge.PLUGINS_VERSION
    assert (inst / "mcp_echo.inx").exists()
    assert (inst / "mcp_echo.py").exists()
    # Installed Python files are executable.
    assert (inst / "mcp_echo.py").stat().st_mode & 0o111


def test_install_is_idempotent(tmp_exchange):
    bridge.install_plugins()
    second = bridge.install_plugins()
    assert second["action"] == "no-op"


def test_needs_inkscape_restart_false_without_install(tmp_exchange):
    bus = MagicMock()
    bus.list_actions.return_value = []
    assert bridge.needs_inkscape_restart(bus) is False


def test_needs_inkscape_restart_true_after_install_before_register(tmp_exchange):
    bridge.install_plugins()
    bus = MagicMock()
    bus.list_actions.return_value = ["copy", "paste"]  # echo action not yet listed
    assert bridge.needs_inkscape_restart(bus) is True


def test_needs_inkscape_restart_false_after_register(tmp_exchange):
    bridge.install_plugins()
    bus = MagicMock()
    bus.list_actions.return_value = [bridge.ECHO_ACTION, "copy"]
    assert bridge.needs_inkscape_restart(bus) is False


def test_bridge_status_snapshot(tmp_exchange):
    snap = bridge.bridge_status()
    assert "installed" in snap
    assert "version" in snap
    assert snap["version"] == bridge.PLUGINS_VERSION
