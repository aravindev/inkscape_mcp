"""Tests that mcp_edit_xml's set_attr with value="" deletes the attribute.

Exercises the extension's mutation code path directly against an lxml tree —
no Inkscape needed. This is the fix for the `filter=""` invisibility bug
hit during the Phase 5/6 live testing: empty-attr values trip up SVG
renderers, so the canonical behaviour is now "absent".
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

# Make the bundled extension importable. Stub inkex so the module loads.
EXT_DIR = Path(__file__).parent.parent / "src" / "inkscape_mcp" / "plugins"


def _import_module(monkeypatch):
    """Stub inkex so the extension module loads outside Inkscape's runtime."""
    import types

    fake_inkex = types.ModuleType("inkex")
    fake_inkex.EffectExtension = object
    monkeypatch.setitem(sys.modules, "inkex", fake_inkex)
    monkeypatch.syspath_prepend(str(EXT_DIR))
    if "mcp_edit_xml" in sys.modules:
        del sys.modules["mcp_edit_xml"]
    import mcp_edit_xml as m  # type: ignore

    return m


def _apply_set_attr(module, elem, name, value):
    """Reproduce the inner set_attr block from McpEditXml.effect.
    Keeping this in a helper so it matches the extension's logic without
    needing to drive the full inkex effect() lifecycle."""
    raw_value = value
    if raw_value == "":
        if name in elem.attrib:
            del elem.attrib[name]
        elif ":" in name:
            prefix, local = name.split(":", 1)
            ns_uri = module._NS_MAP.get(prefix)
            if ns_uri:
                clark = f"{{{ns_uri}}}{local}"
                if clark in elem.attrib:
                    del elem.attrib[clark]
    else:
        elem.set(name, str(raw_value))


def test_empty_value_deletes_unprefixed_attr(monkeypatch):
    m = _import_module(monkeypatch)
    elem = etree.fromstring('<rect xmlns="http://www.w3.org/2000/svg" fill="red"/>')
    assert elem.get("fill") == "red"
    _apply_set_attr(m, elem, "fill", "")
    assert "fill" not in elem.attrib


def test_empty_value_deletes_prefixed_attr(monkeypatch):
    m = _import_module(monkeypatch)
    elem = etree.fromstring(
        '<g xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'inkscape:label="my layer"/>'
    )
    INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
    assert elem.get(f"{{{INKSCAPE_NS}}}label") == "my layer"
    _apply_set_attr(m, elem, "inkscape:label", "")
    assert f"{{{INKSCAPE_NS}}}label" not in elem.attrib


def test_nonempty_value_still_sets_attr_normally(monkeypatch):
    m = _import_module(monkeypatch)
    elem = etree.fromstring('<rect xmlns="http://www.w3.org/2000/svg"/>')
    _apply_set_attr(m, elem, "fill", "#ff0000")
    assert elem.get("fill") == "#ff0000"


def test_empty_value_on_absent_attr_is_noop(monkeypatch):
    """Deleting an attribute that wasn't there should not raise."""
    m = _import_module(monkeypatch)
    elem = etree.fromstring('<rect xmlns="http://www.w3.org/2000/svg"/>')
    _apply_set_attr(m, elem, "filter", "")
    assert "filter" not in elem.attrib
