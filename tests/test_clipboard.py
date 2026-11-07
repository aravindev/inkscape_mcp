"""Tests for SVG fragment normalization."""

from __future__ import annotations

from inkscape_mcp.clipboard import normalize_fragment_to_viewbox


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
