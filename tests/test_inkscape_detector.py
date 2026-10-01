"""Platform-aware Inkscape detection."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from inkscape_mcp import inkscape_detector
from inkscape_mcp.inkscape_detector import InkscapeDetector, _fallback_paths


def test_macos_fallbacks_include_app_bundle():
    paths = [str(p) for p in _fallback_paths("darwin")]
    assert "/Applications/Inkscape.app/Contents/MacOS/inkscape" in paths
    assert "/opt/homebrew/bin/inkscape" in paths


def test_windows_fallbacks_prefer_console_build():
    paths = [Path(p).name for p in _fallback_paths("win32")]
    assert paths[0] == "inkscape.com"
    assert "inkscape.exe" in paths


def test_linux_fallbacks_unchanged():
    paths = [str(p) for p in _fallback_paths("linux")]
    assert "/usr/bin/inkscape" in paths
    assert "/snap/bin/inkscape" in paths


@pytest.mark.skipif(os.name == "nt", reason="POSIX exec bits")
def test_detector_uses_fallback_when_not_on_path(tmp_path, monkeypatch):
    fake = tmp_path / "inkscape"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(inkscape_detector.shutil, "which", lambda _name: None)
    monkeypatch.setattr(inkscape_detector, "_fallback_paths", lambda platform=None: (fake,))
    assert InkscapeDetector().detect_inkscape_installation() == str(fake)


def test_detector_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(inkscape_detector.shutil, "which", lambda _name: None)
    monkeypatch.setattr(inkscape_detector, "_fallback_paths", lambda platform=None: ())
    assert InkscapeDetector().detect_inkscape_installation() is None
