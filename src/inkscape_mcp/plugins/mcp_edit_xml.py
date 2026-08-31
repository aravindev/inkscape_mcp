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


def _parse_svg_fragment(xml_str: str) -> list:
    """Parse an XML fragment into its top-level elements, in document order.

    Without the wrapper, lxml gives the user-supplied fragment ``xmlns=""``
    which Inkscape refuses to render. The wrapper declares the SVG default
    namespace plus the usual Inkscape/sodipodi/xlink/rdf/dc prefixes so any
    element the caller writes ends up in the correct namespace.

    Several sibling elements are allowed. Requiring exactly one made it impossible to
    insert a group of shapes in a single undoable edit — and `insert_svg`, which builds
    on this, is *typically* handed several siblings.
    """
    nsdecls = " ".join(f'xmlns:{p}="{u}"' for p, u in _NS_MAP.items())
    wrapped = f'<root xmlns="{_NS_MAP["svg"]}" {nsdecls}>{xml_str}</root>'
    root = etree.fromstring(wrapped.encode("utf-8"))
    elements = [c for c in root if isinstance(c.tag, str)]
    if not elements:
        raise ValueError("fragment contained no elements")
    return elements


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

        # An XPath can legitimately evaluate to something other than a node-set —
        # `//@id` yields strings, `count(...)` a float. Those have no .append/.getparent,
        # and AttributeError isn't in the mutation handler below, so the exception escaped
        # effect(), result.json was never written, and the caller sat out the full 15s
        # timeout instead of getting an error.
        if not isinstance(matches, list):
            _write_result(
                {
                    "ok": False,
                    "error": (
                        f"xpath {xpath!r} evaluated to {type(matches).__name__}, not elements — "
                        f"edit_xml needs an element node-set"
                    ),
                }
            )
            return

        if not matches:
            _write_result(
                {
                    "ok": False,
                    "error": f"xpath matched no nodes: {xpath!r}",
                }
            )
            return

        non_elements = [m for m in matches if not isinstance(m, etree._Element)]
        if non_elements:
            _write_result(
                {
                    "ok": False,
                    "error": (
                        f"xpath {xpath!r} matched {len(non_elements)} non-element result(s) "
                        f"(e.g. {type(non_elements[0]).__name__}) — edit_xml only mutates elements"
                    ),
                }
            )
            return

        affected = 0
        try:
            for node in matches:
                if action == "append":
                    for frag in _parse_svg_fragment(spec["xml"]):
                        node.append(frag)
                elif action == "insert_before":
                    for frag in _parse_svg_fragment(spec["xml"]):
                        node.addprevious(frag)
                elif action == "insert_after":
                    # Reversed: each addnext lands immediately after `node`, so
                    # inserting in reverse preserves the fragment's own order.
                    for frag in reversed(_parse_svg_fragment(spec["xml"])):
                        node.addnext(frag)
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
                    frags = _parse_svg_fragment(spec["xml"])
                    parent.replace(node, frags[0])
                    # Any further siblings follow the one that took node's place.
                    for extra in reversed(frags[1:]):
                        frags[0].addnext(extra)
                affected += 1
        except (KeyError, ValueError, etree.XMLSyntaxError) as exc:
            _write_result({"ok": False, "error": f"mutation failed: {exc}"})
            return

        # Name the document that was actually mutated. Inkscape runs an effect against
        # the ACTIVE desktop and offers no way to pick another, so this is the caller's
        # only way to confirm the edit landed where they intended.
        _write_result(
            {
                "ok": True,
                "action": action,
                "xpath": xpath,
                "affected": affected,
                "active_document": _document_identity(root),
            }
        )


def _write_result(payload: dict) -> None:
    (EXCHANGE_DIR / "result.json").write_text(json.dumps(payload))


def _document_identity(root) -> dict:
    """Identify the document this extension ran against.

    Reports only what is knowable: `path` is set ONLY when `sodipodi:docname` is already
    absolute. Resolving a bare docname against the CWD would be wrong — an extension's
    CWD is the extension install directory, not the document's location.

    Duplicated in mcp_inspect.py: these plugins are copied into Inkscape's extension
    directory as standalone scripts, so they cannot share a module.
    """
    docname = root.get("{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname") or ""
    path = docname if docname.startswith("/") or (len(docname) > 2 and docname[1] == ":") else ""
    return {"docname": docname, "path": path, "root_id": root.get("id") or ""}


if __name__ == "__main__":
    try:
        McpEditXml().run()
    except SystemExit:
        raise
    except Exception:
        EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
        (EXCHANGE_DIR / "stderr.txt").write_text(traceback.format_exc())
        raise
