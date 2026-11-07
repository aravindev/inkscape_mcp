"""Read-only diagnostics; run with --noconftest to skip GUI integration setup."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inkscape_mcp import bus_manager, extension_bridge, platform_support, win_dbus_client
from inkscape_mcp.tools import live, system


@pytest.fixture
def diagnostic_env(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("diagnostics must not launch processes"))
    monkeypatch.setattr(bus_manager, "ensure_bus", forbidden)
    monkeypatch.setattr(bus_manager, "ensure_inkscape", forbidden)
    monkeypatch.setattr(bus_manager.subprocess, "Popen", forbidden)
    monkeypatch.setattr(bus_manager.subprocess, "run", forbidden)
    get_bus = Mock(side_effect=AssertionError("managed diagnostics must not use _get_bus"))
    monkeypatch.setattr(live, "_get_bus", get_bus)
    monkeypatch.setattr(bus_manager, "manages_bus", lambda: True)
    monkeypatch.setattr(platform_support, "is_macos", lambda: True)
    monkeypatch.setattr(platform_support, "is_windows", lambda: False)
    monkeypatch.setattr(bus_manager, "find_dbus_daemon", lambda: "/mock/dbus-daemon")
    monkeypatch.setattr(platform_support, "profile_dir", lambda: Path("/mock/isolated-profile"))
    monkeypatch.setattr(platform_support, "bundled_python", lambda executable: "/mock/python")
    preference = {"profile": "/mock/isolated-profile", "configured": True}
    monkeypatch.setattr(platform_support, "python_preference_status", lambda: preference)
    metadata = {"installed": True, "version": "test-version", "install_dir": "/mock/extensions"}
    monkeypatch.setattr(extension_bridge, "bridge_status", lambda: metadata.copy())
    restart = Mock(return_value=True)
    monkeypatch.setattr(extension_bridge, "needs_inkscape_restart", restart)
    address_file = Mock()
    address_file.exists.return_value = True
    address_file.read_text.return_value = "unix:path=/mock/bus,guid=123\n"
    monkeypatch.setattr(bus_manager, "ADDRESS_FILE", address_file)
    find_gdbus = Mock(return_value="/mock/gdbus")
    monkeypatch.setattr(bus_manager, "find_gdbus", find_gdbus)
    bus = Mock()
    bus.is_available.return_value = True
    client = Mock(return_value=bus)
    monkeypatch.setattr(win_dbus_client, "GDBusInkscapeDBus", client)
    env = SimpleNamespace(
        config=SimpleNamespace(inkscape_executable="/mock/inkscape"),
        address_file=address_file,
        bus=bus,
        client=client,
        find_gdbus=find_gdbus,
        get_bus=get_bus,
        restart=restart,
        metadata=metadata,
        preference=preference,
    )
    yield env
    forbidden.assert_not_called()


async def diagnostics(env):
    result = await system.inkscape_system("diagnostics", config=env.config)
    assert result["success"] is True
    return result["data"]["bridge"]


def assert_metadata(bridge, env):
    for key, value in env.metadata.items():
        assert bridge[key] == value
    assert bridge["platform"]["profile_dir"] == "/mock/isolated-profile"
    assert bridge["platform"]["python_preference"] == env.preference


@pytest.mark.parametrize("platform", ["macOS", "Windows"])
async def test_existing_managed_bus_is_probed_without_launch(diagnostic_env, monkeypatch, platform):
    env = diagnostic_env
    monkeypatch.setattr(platform_support, "is_macos", lambda: platform == "macOS")
    monkeypatch.setattr(platform_support, "is_windows", lambda: platform == "Windows")
    bridge = await diagnostics(env)
    assert bridge["live"] is True
    assert bridge["needs_restart"] is True
    assert bridge["platform"]["system"] == platform
    assert_metadata(bridge, env)
    env.find_gdbus.assert_called_once_with("/mock/inkscape")
    env.address_file.read_text.assert_called_once_with(encoding="utf-8")
    env.client.assert_called_once_with("/mock/gdbus", "unix:path=/mock/bus,guid=123")
    env.get_bus.assert_not_called()
    env.restart.assert_called_once_with(env.bus)


@pytest.mark.parametrize(
    ("state", "message"),
    [("missing_gdbus", "gdbus not found"), ("missing_address", "no saved managed bus address")],
)
async def test_missing_dependencies_preserve_details(diagnostic_env, state, message):
    env = diagnostic_env
    if state == "missing_gdbus":
        env.find_gdbus.return_value = None
    else:
        env.address_file.exists.return_value = False
    bridge = await diagnostics(env)
    assert bridge["live"] is False
    assert message in bridge["probe"]
    assert_metadata(bridge, env)
    env.client.assert_not_called()
    env.address_file.read_text.assert_not_called()
    env.get_bus.assert_not_called()


@pytest.mark.parametrize("address", ["", " \n", "garbage", "autolaunch:", "unix:path=/bus;autolaunch:"])
async def test_invalid_addresses_are_not_probed(diagnostic_env, address):
    env = diagnostic_env
    env.address_file.read_text.return_value = address
    bridge = await diagnostics(env)
    assert bridge["live"] is False
    assert "invalid saved managed bus address" in bridge["probe"]
    assert_metadata(bridge, env)
    env.client.assert_not_called()
    env.get_bus.assert_not_called()


@pytest.mark.parametrize("failure", ["read", "construct", "probe"])
async def test_probe_errors_preserve_details(diagnostic_env, failure):
    env = diagnostic_env
    target = {"read": env.address_file.read_text, "construct": env.client, "probe": env.bus.is_available}[failure]
    target.side_effect = RuntimeError("probe unavailable")
    bridge = await diagnostics(env)
    assert bridge["live"] is False
    assert "probe unavailable" in bridge["probe"]
    assert_metadata(bridge, env)
    env.get_bus.assert_not_called()


async def test_stale_bus_is_not_replaced(diagnostic_env):
    env = diagnostic_env
    env.bus.is_available.return_value = False
    bridge = await diagnostics(env)
    assert bridge["live"] is False
    assert "existing bus" in bridge["probe"]
    assert_metadata(bridge, env)
    env.restart.assert_not_called()


async def test_timeout_preserves_details(diagnostic_env, monkeypatch):
    async def timeout(awaitable, *, timeout):
        assert timeout == 10.0
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(system.asyncio, "wait_for", timeout)
    bridge = await diagnostics(diagnostic_env)
    assert bridge["live"] is False
    assert bridge["probe"] == "timed out after 10s"
    assert_metadata(bridge, diagnostic_env)
    diagnostic_env.client.assert_not_called()


async def test_platform_field_failure_is_isolated(diagnostic_env, monkeypatch):
    monkeypatch.setattr(platform_support, "bundled_python", Mock(side_effect=OSError("python missing")))
    bridge = await diagnostics(diagnostic_env)
    assert bridge["live"] is True
    assert_metadata(bridge, diagnostic_env)
    assert bridge["platform"]["bundled_python"] is None
    assert bridge["platform"]["errors"] == {"bundled_python": "python missing"}


async def test_bridge_metadata_failure_does_not_hide_platform_or_probe(diagnostic_env, monkeypatch):
    monkeypatch.setattr(extension_bridge, "bridge_status", Mock(side_effect=OSError("metadata unavailable")))
    bridge = await diagnostics(diagnostic_env)
    assert bridge["error"] == "metadata unavailable"
    assert bridge["live"] is True
    assert bridge["platform"]["python_preference"] == diagnostic_env.preference


async def test_restart_failure_does_not_hide_live_status(diagnostic_env):
    diagnostic_env.restart.side_effect = RuntimeError("restart unavailable")
    bridge = await diagnostics(diagnostic_env)
    assert bridge["live"] is True
    assert "restart unavailable" in bridge["probe"]
    assert_metadata(bridge, diagnostic_env)


async def test_linux_uses_existing_get_bus(diagnostic_env, monkeypatch):
    env = diagnostic_env
    monkeypatch.setattr(bus_manager, "manages_bus", lambda: False)
    monkeypatch.setattr(platform_support, "is_macos", lambda: False)
    env.get_bus.side_effect = None
    env.get_bus.return_value = env.bus
    bridge = await diagnostics(env)
    assert bridge["live"] is True
    assert bridge["platform"]["system"] == "Linux"
    env.get_bus.assert_called_once_with(env.config)
    env.find_gdbus.assert_not_called()
    env.address_file.exists.assert_not_called()
    env.client.assert_not_called()
