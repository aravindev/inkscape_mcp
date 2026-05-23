"""Tests for the system clipboard helper."""

from __future__ import annotations

import os
import subprocess

import pytest

from inkscape_mcp.clipboard import detect_session, normalize_fragment_to_viewbox, stage_svg_fragment


def test_detect_session():
    s = detect_session()
    assert s in {"x11", "wayland", ""}


@pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="no display available",
)
def test_stage_and_read_back(tmp_path):
    fragment = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
    sess = detect_session()
    if sess == "":
        pytest.skip("display present but clipboard tool missing")
    stage_svg_fragment(fragment)
    if sess == "x11":
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/x-inkscape-svg", "-o"],
            capture_output=True,
            timeout=5,
        )
        assert b"<rect" in out.stdout
    elif sess == "wayland":
        out = subprocess.run(
            ["wl-paste", "--type", "image/x-inkscape-svg"],
            capture_output=True,
            timeout=5,
        )
        assert b"<rect" in out.stdout


def test_normalize_fragment(tmp_path):
    src = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" '
        'viewBox="0 0 200 100"><rect x="20" y="20" width="40" height="40"/></svg>'
    )
    out = normalize_fragment_to_viewbox(src, target_width=210, target_height=297)
    assert "viewBox=" in out
    assert "<rect" in out


def test_normalize_fragment_without_viewbox():
    src = '<svg xmlns="http://www.w3.org/2000/svg" width="50px" height="50px"><circle cx="25" cy="25" r="20"/></svg>'
    out = normalize_fragment_to_viewbox(src, target_width=100, target_height=100)
    assert 'viewBox="0 0 100 100"' in out
    assert "<circle" in out


def test_normalize_fragment_scales_when_oversized():
    # Source 400x400 into 100x100 target — should produce a scale<1 transform.
    src = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400"/></svg>'
    out = normalize_fragment_to_viewbox(src, target_width=100, target_height=100)
    assert "scale(0.25" in out


def test_stage_raises_when_no_session(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="No graphical session"):
        stage_svg_fragment("<svg/>")
