"""Per-OS Inkscape directory resolution."""

from __future__ import annotations

from pathlib import Path

from inkscape_mcp.platform_paths import system_extension_dirs, user_extensions_dir, user_profile_dir


def test_macos_user_dir_is_application_support(monkeypatch):
    monkeypatch.delenv("INKSCAPE_PROFILE_DIR", raising=False)
    p = user_extensions_dir("darwin")
    assert p == Path.home() / "Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions"


def test_windows_user_dir_uses_appdata(monkeypatch):
    monkeypatch.delenv("INKSCAPE_PROFILE_DIR", raising=False)
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    assert user_profile_dir("win32") == Path("/fake/appdata/inkscape")


def test_linux_user_dir_honours_xdg(monkeypatch):
    monkeypatch.delenv("INKSCAPE_PROFILE_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fake/xdg")
    assert user_profile_dir("linux") == Path("/fake/xdg/inkscape")


def test_profile_dir_env_overrides_everything(monkeypatch):
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", "/custom/profile")
    for plat in ("linux", "darwin", "win32"):
        assert user_profile_dir(plat) == Path("/custom/profile")


def test_macos_system_dir_derived_from_binary(tmp_path):
    exe = tmp_path / "Inkscape.app/Contents/MacOS/inkscape"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    dirs = system_extension_dirs(exe, "darwin")
    assert dirs[0] == exe.resolve().parent.parent / "Resources/share/inkscape/extensions"


def test_system_dirs_are_deduplicated():
    dirs = system_extension_dirs("/Applications/Inkscape.app/Contents/MacOS/inkscape", "darwin")
    assert len(dirs) == len(set(dirs))
