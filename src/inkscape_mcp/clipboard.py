"""SVG fragment normalization helpers."""

from __future__ import annotations

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"


def _strip_unit(value: str) -> float:
    """Strip a trailing CSS-style unit (px, mm, pt, etc.) and return the numeric part."""
    s = value.strip()
    end = len(s)
    for i, ch in enumerate(s):
        if not (ch.isdigit() or ch in ".-+eE"):
            end = i
            break
    if end == 0:
        raise ValueError(f"Cannot parse numeric value from {value!r}")
    return float(s[:end])


def normalize_fragment_to_viewbox(
    svg_xml: str,
    target_width: float,
    target_height: float,
    target_units: str = "px",
) -> str:
    """Rewrite the fragment's outer <svg> width/height/viewBox to match the target doc.

    The fragment's intrinsic geometry is centred within the target viewBox at
    its natural size. If the fragment is larger than the target on either axis,
    it is uniformly scaled down to fit while preserving aspect ratio.
    """
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    root = etree.fromstring(svg_xml.encode("utf-8"), parser=parser)

    # Determine source extents from viewBox, or derive from width/height.
    vb = root.get("viewBox")
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) != 4:
            raise ValueError(f"Malformed viewBox: {vb!r}")
        _src_x, _src_y, src_w, src_h = (float(p) for p in parts)
    else:
        w_attr = root.get("width")
        h_attr = root.get("height")
        if not w_attr or not h_attr:
            raise ValueError("Fragment lacks both viewBox and width/height; cannot normalize.")
        src_w = _strip_unit(w_attr)
        src_h = _strip_unit(h_attr)

    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"Non-positive source extents: {src_w}x{src_h}")

    # Uniform fit-scale if the source would overflow the target.
    scale = min(1.0, target_width / src_w, target_height / src_h)
    placed_w = src_w * scale
    placed_h = src_h * scale

    unit_suffix = "" if target_units == "px" else target_units
    root.set("width", f"{target_width}{unit_suffix}")
    root.set("height", f"{target_height}{unit_suffix}")
    root.set("viewBox", f"0 0 {target_width} {target_height}")

    # Wrap children in a <g> that centres the original geometry within the new viewBox.
    tx = (target_width - placed_w) / 2.0
    ty = (target_height - placed_h) / 2.0
    g = etree.SubElement(root, f"{{{SVG_NS}}}g")
    g.set("transform", f"translate({tx} {ty}) scale({scale})")

    # Move all non-<g> existing children into the wrapper, preserving order.
    for child in list(root):
        if child is g:
            continue
        root.remove(child)
        g.append(child)
    # Append wrapper last so it's the only direct child holding content.
    root.remove(g)
    root.append(g)

    # Ensure the root has the SVG namespace declared without a prefix.
    if root.tag != f"{{{SVG_NS}}}svg":
        # Rename root into the SVG namespace if it wasn't already.
        new_root = etree.Element(f"{{{SVG_NS}}}svg", nsmap={None: SVG_NS})
        for k, v in root.attrib.items():
            new_root.set(k, v)
        for child in list(root):
            new_root.append(child)
        root = new_root

    return str(etree.tostring(root, xml_declaration=False, encoding="unicode"))
