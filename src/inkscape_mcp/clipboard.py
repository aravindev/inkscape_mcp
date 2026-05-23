"""System clipboard helper for staging SVG fragments into Inkscape's paste path."""

from __future__ import annotations

import os
import shutil
import subprocess

from lxml import etree

INKSCAPE_SVG_MIME = "image/x-inkscape-svg"
SVG_NS = "http://www.w3.org/2000/svg"
_CLIPBOARD_TIMEOUT = 5.0


def detect_session() -> str:
    """Return 'wayland', 'x11', or '' if no display is reachable.

    Prefers Wayland when both env vars are present (Xwayland fallback would
    still be usable but a native Wayland session should drive wl-copy).
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("wl-copy"):
            return "wayland"
        return ""
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            return "x11"
        return ""
    return ""


def stage_svg_fragment(svg_xml: str) -> None:
    """Push an SVG fragment to the system clipboard with Inkscape's MIME."""
    session = detect_session()
    if session == "x11":
        cmd = ["xclip", "-selection", "clipboard", "-t", INKSCAPE_SVG_MIME]
    elif session == "wayland":
        cmd = ["wl-copy", "--type", INKSCAPE_SVG_MIME]
    else:
        # Distinguish "no display" from "display set but tool missing" for better diagnostics.
        if os.environ.get("WAYLAND_DISPLAY"):
            raise RuntimeError("Wayland session detected but 'wl-copy' is not on PATH; install wl-clipboard.")
        if os.environ.get("DISPLAY"):
            raise RuntimeError("X11 session detected but 'xclip' is not on PATH; install xclip.")
        raise RuntimeError("No graphical session reachable (neither $WAYLAND_DISPLAY nor $DISPLAY is set).")

    # xclip needs to daemonise to own the selection — pipe its stdout/stderr to DEVNULL
    # so the parent isn't kept alive waiting on output fds. wl-copy behaves the same way.
    try:
        subprocess.run(  # noqa: S603 — cmd is built from a fixed allowlist (xclip / wl-copy)
            cmd,
            input=svg_xml.encode("utf-8"),
            check=True,
            timeout=_CLIPBOARD_TIMEOUT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Clipboard tool {cmd[0]} timed out after {_CLIPBOARD_TIMEOUT}s") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Clipboard tool {cmd[0]} failed with exit code {exc.returncode}") from exc


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

    return etree.tostring(root, xml_declaration=False, encoding="unicode")
