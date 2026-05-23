#!/usr/bin/env python3
"""mcp_edit_xml — structural XML edit applied to the live Inkscape document.

This is the inkex transport for ``inkscape_live(operation="edit_xml")``. By
routing edits through an EffectExtension, the mutation becomes a single
undoable command in Inkscape's normal flow — preserving the user's undo
history (unlike the older ``document-revert`` path which discarded it).

Reads ``~/.cache/inkscape_mcp/exchange/input.json`` describing the edit:

    {
        "xpath":  "//svg:defs",
        "action": "append|insert_before|insert_after|replace|remove|set_attr|set_text",
        "xml":    "<filter id=\"x\"/>",      # append/insert_*/replace
        "name":   "fill", "value": "#ff0000",  # set_attr
        "text":   "new text"                   # set_text
    }

**`set_attr` empty-string semantics:** ``value=""`` deletes the named
attribute (canonical "absent") rather than writing ``attr=""``. Several SVG
renderers — Inkscape 1.4 included — treat the empty-string form as a
malformed reference and silently hide the element. See the project
plan §4 Phase 5 lessons for the discovery history.

Writes ``~/.cache/inkscape_mcp/exchange/result.json`` with either
``{"ok": True, "action": ..., "xpath": ..., "affected": <int>}`` on success
or ``{"ok": False, "error": "<message>"}`` on failure. Unexpected
exceptions also get their traceback dumped to ``stderr.txt`` before being
re-raised so Inkscape logs them.
"""

import json
import os
import traceback
from pathlib import Path

import inkex
from lxml import etree

EXCHANGE_DIR = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

_NS_MAP = {
    "svg": "http://www.w3.org/2000/svg",
    "xlink": "http://www.w3.org/1999/xlink",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_EDIT_XML_ACTIONS = frozenset(
    {
        "append",
        "insert_before",
        "insert_after",
        "remove",
        "set_attr",
        "set_text",
        "replace",
    }
)


def _parse_svg_fragment(xml_str: str) -> "etree._Element":
    """Parse an XML fragment, declaring SVG namespaces so children inherit them.

    Without the wrapper, lxml gives the user-supplied fragment ``xmlns=""``
    which Inkscape refuses to render. The wrapper declares the SVG default
    namespace plus the usual Inkscape/sodipodi/xlink/rdf/dc prefixes so any
    element the caller writes ends up in the correct namespace.
    """
    nsdecls = " ".join(f'xmlns:{p}="{u}"' for p, u in _NS_MAP.items())
    wrapped = f'<root xmlns="{_NS_MAP["svg"]}" {nsdecls}>{xml_str}</root>'
    root = etree.fromstring(wrapped.encode("utf-8"))
    if len(root) != 1:
        raise ValueError(f"fragment must have exactly one top-level element, got {len(root)}")
    return root[0]


class McpEditXml(inkex.EffectExtension):
    def effect(self) -> None:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            spec = json.loads((EXCHANGE_DIR / "input.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _write_result({"ok": False, "error": f"could not read input.json: {exc}"})
            return

        if not isinstance(spec, dict):
            _write_result({"ok": False, "error": "input.json must decode to an object"})
            return

        xpath = spec.get("xpath")
        if not xpath or not isinstance(xpath, str):
            _write_result({"ok": False, "error": "'xpath' is required"})
            return

        action = spec.get("action")
        if action not in _EDIT_XML_ACTIONS:
            _write_result(
                {
                    "ok": False,
                    "error": (f"unknown action {action!r}; valid: {sorted(_EDIT_XML_ACTIONS)}"),
                }
            )
            return

        # self.svg is the <svg> root element in modern inkex; older versions
        # exposed an ElementTree. Handle both so the extension is portable.
        root = self.svg.getroot() if hasattr(self.svg, "getroot") else self.svg

        try:
            matches = root.xpath(xpath, namespaces=_NS_MAP)
        except etree.XPathEvalError as exc:
            _write_result({"ok": False, "error": f"bad xpath {xpath!r}: {exc}"})
            return

        if not matches:
            _write_result(
                {
                    "ok": False,
                    "error": f"xpath matched no nodes: {xpath!r}",
                }
            )
            return

        affected = 0
        try:
            for node in matches:
                if action == "append":
                    node.append(_parse_svg_fragment(spec["xml"]))
                elif action == "insert_before":
                    node.addprevious(_parse_svg_fragment(spec["xml"]))
                elif action == "insert_after":
                    node.addnext(_parse_svg_fragment(spec["xml"]))
                elif action == "remove":
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                elif action == "set_attr":
                    # Empty string = delete the attribute (canonical "absent")
                    # rather than write attr="". Some SVG renderers treat
                    # attr="" as malformed and hide the element entirely
                    # (notably filter="" on Inkscape 1.4). Callers wanting an
                    # explicit empty string can use set_text on a child or
                    # bypass via edit_xml(replace).
                    raw_value = spec.get("value", "")
                    if raw_value == "":
                        # Pop both Clark-notation and prefix-mapped forms.
                        attr_name = spec["name"]
                        if attr_name in node.attrib:
                            del node.attrib[attr_name]
                        else:
                            # Try resolving namespaced form like "inkscape:label".
                            if ":" in attr_name:
                                prefix, local = attr_name.split(":", 1)
                                ns_uri = _NS_MAP.get(prefix)
                                if ns_uri:
                                    clark = f"{{{ns_uri}}}{local}"
                                    if clark in node.attrib:
                                        del node.attrib[clark]
                    else:
                        node.set(spec["name"], str(raw_value))
                elif action == "set_text":
                    node.text = spec.get("text", "")
                elif action == "replace":
                    parent = node.getparent()
                    if parent is None:
                        raise ValueError("cannot replace the document root")
                    parent.replace(node, _parse_svg_fragment(spec["xml"]))
                affected += 1
        except (KeyError, ValueError, etree.XMLSyntaxError) as exc:
            _write_result({"ok": False, "error": f"mutation failed: {exc}"})
            return

        _write_result(
            {
                "ok": True,
                "action": action,
                "xpath": xpath,
                "affected": affected,
            }
        )


def _write_result(payload: dict) -> None:
    (EXCHANGE_DIR / "result.json").write_text(json.dumps(payload))


if __name__ == "__main__":
    try:
        McpEditXml().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
