"""Gradient stop manipulation via SVG XML mutation."""

from __future__ import annotations

import time
from typing import Any

from lxml import etree
from pydantic import BaseModel

SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"


class GradientResult(BaseModel):
    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


def _parse_offset(raw: str) -> float:
    """Normalise Inkscape's "0", "0%", "0.0" offsets to a 0-1 float."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    if s.endswith("%"):
        return float(s[:-1]) / 100.0
    v = float(s)
    # Bare numbers in SVG are already 0..1 per spec; clamp defensively.
    return v


def _format_offset_pct(frac: float) -> str:
    """Render a 0..1 fraction as a clean percentage string."""
    pct = frac * 100.0
    if abs(pct - round(pct)) < 1e-6:
        return f"{round(pct)}%"
    return f"{pct:g}%"


XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _find_gradient(root: etree._Element, gradient_id: str) -> etree._Element | None:
    for tag in ("linearGradient", "radialGradient"):
        for el in root.iter(f"{SVG}{tag}"):
            if el.get("id") == gradient_id:
                return el
    return None


def _resolve_stop_holder(root: etree._Element, grad: etree._Element) -> etree._Element:
    """Follow xlink:href until we reach the gradient that actually holds the <stop> children.

    Inkscape stores every gradient as a pair: one element holding the stops, and a second
    that references it via ``xlink:href`` and carries the geometry
    (``gradientUnits="userSpaceOnUse"``, x1/y1/x2/y2). It is the *referencing* id that shows
    up in ``fill="url(#…)"``, so that is the id a caller will naturally pass. Reading or
    writing stops on it directly finds none — and per SVG 1.1 adding a stop to a referencing
    gradient stops the inheritance, collapsing a multi-stop ramp to a flat colour.
    """
    seen: set[int] = set()
    current = grad
    while True:
        if list(current.iter(f"{SVG}stop")):
            return current
        seen.add(id(current))
        href = current.get(XLINK_HREF) or current.get("href")
        if not href or not href.startswith("#"):
            return current
        target = _find_gradient(root, href[1:])
        if target is None or id(target) in seen:
            return current
        current = target


def _stops(grad: etree._Element) -> list[etree._Element]:
    return list(grad.iter(f"{SVG}stop"))


def _stop_color_opacity(stop: etree._Element) -> dict[str, str]:
    """Extract color/opacity from a stop, honouring both attr and style forms."""
    color = stop.get("stop-color") or ""
    opacity = stop.get("stop-opacity") or ""
    style = stop.get("style") or ""
    if style:
        for part in style.split(";"):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "stop-color" and not color:
                color = v
            elif k == "stop-opacity" and not opacity:
                opacity = v
    return {"stop_color": color, "stop_opacity": opacity}


def _set_stop_color(stop: etree._Element, color: str) -> None:
    """Write color to both attr and style so Inkscape picks it up consistently."""
    stop.set("stop-color", color)
    style = stop.get("style") or ""
    parts = [p for p in style.split(";") if p.strip() and not p.strip().startswith("stop-color")]
    parts.append(f"stop-color:{color}")
    stop.set("style", ";".join(parts))


def _num(raw: str | None) -> float | None:
    """Parse a gradient coordinate attribute, tolerating absence and junk."""
    if raw is None:
        return None
    try:
        return float(str(raw).strip().rstrip("%"))
    except ValueError:
        return None


def _units(grad: etree._Element) -> str:
    """gradientUnits, defaulting to the SVG spec's objectBoundingBox."""
    return grad.get("gradientUnits") or "objectBoundingBox"


def _user_space(grad: etree._Element) -> bool:
    return _units(grad) == "userSpaceOnUse"


def _parse(input_path: str) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(input_path, parser)


def _write(tree: etree._ElementTree, output_path: str) -> None:
    from ._svg_io import write_tree

    write_tree(tree, output_path)


def _result(
    success: bool,
    operation: str,
    message: str,
    data: dict[str, Any],
    start: float,
    error: str = "",
) -> dict[str, Any]:
    return GradientResult(
        success=success,
        operation=operation,
        message=message,
        data=data,
        execution_time_ms=(time.time() - start) * 1000,
        error=error,
    ).model_dump()


async def inkscape_gradient(
    operation: str,
    input_path: str,
    output_path: str,
    gradient_id: str = "",
    stop_offset: str = "",
    stop_color: str = "",
    stop_opacity: float = 1.0,
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Add/remove/recolor gradient stops; convert linear↔radial."""
    start = time.time()
    try:
        if not input_path:
            return _result(False, operation, "input_path required", {}, start, "ValueError")
        tree = _parse(input_path)
        root = tree.getroot()

        grad = _find_gradient(root, gradient_id)
        if grad is None:
            return _result(False, operation, f"gradient '{gradient_id}' not found", {}, start, "NotFound")

        # Stop reads and writes always target the gradient that owns the <stop> children,
        # which may be a different element reached through xlink:href.
        holder = _resolve_stop_holder(root, grad)
        holder_id = holder.get("id", "")
        via_href = holder is not grad

        if operation == "list_stops":
            stops = [
                {
                    "id": s.get("id", ""),
                    "offset": s.get("offset", ""),
                    **_stop_color_opacity(s),
                }
                for s in _stops(holder)
            ]
            return _result(
                True,
                operation,
                f"found {len(stops)} stops",
                {
                    "gradient_id": gradient_id,
                    "stops_from": holder_id,
                    "inherited_via_href": via_href,
                    "stops": stops,
                },
                start,
            )

        if operation == "add_stop":
            target = _parse_offset(stop_offset)
            new_stop = etree.SubElement(holder, f"{SVG}stop")
            new_stop.set("offset", _format_offset_pct(target))
            _set_stop_color(new_stop, stop_color or "#000000")
            new_stop.set("stop-opacity", f"{stop_opacity:g}")
            # Sort stops by offset so the gradient renders monotonically.
            sorted_stops = sorted(_stops(holder), key=lambda s: _parse_offset(s.get("offset", "0")))
            for s in _stops(holder):
                holder.remove(s)
            for s in sorted_stops:
                holder.append(s)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"added stop at {target * 100:g}%",
                {
                    "gradient_id": gradient_id,
                    "modified_gradient": holder_id,
                    "inherited_via_href": via_href,
                    "offset": target,
                },
                start,
            )

        if operation == "remove_stop":
            target = _parse_offset(stop_offset)
            stops = _stops(holder)
            if not stops:
                return _result(False, operation, "no stops to remove", {}, start, "NotFound")
            closest = min(stops, key=lambda s: abs(_parse_offset(s.get("offset", "0")) - target))
            holder.remove(closest)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"removed stop near {target * 100:g}%",
                {"gradient_id": gradient_id, "modified_gradient": holder_id},
                start,
            )

        if operation == "set_stop_color":
            target = _parse_offset(stop_offset)
            stops = _stops(holder)
            if not stops:
                return _result(False, operation, "no stops to recolor", {}, start, "NotFound")
            match = min(stops, key=lambda s: abs(_parse_offset(s.get("offset", "0")) - target))
            _set_stop_color(match, stop_color or "#000000")
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"recoloured stop near {target * 100:g}% to {stop_color}",
                {"gradient_id": gradient_id, "modified_gradient": holder_id, "stop_color": stop_color},
                start,
            )

        if operation == "convert_to_linear":
            if grad.tag != f"{SVG}radialGradient":
                return _result(False, operation, "gradient is not radial", {}, start, "InvalidState")
            cx, cy, r = (_num(grad.get(a)) for a in ("cx", "cy", "r"))
            grad.tag = f"{SVG}linearGradient"
            for attr in ("cx", "cy", "r", "fx", "fy", "fr"):
                grad.attrib.pop(attr, None)
            # A left-to-right line across the circle's diameter reproduces the ramp's extent.
            if _user_space(grad) and None not in (cx, cy, r):
                coords = {"x1": cx - r, "y1": cy, "x2": cx + r, "y2": cy}  # type: ignore[operator]
            else:
                coords = {"x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5}
            for attr, value in coords.items():
                grad.set(attr, f"{value:g}")
            _write(tree, output_path)
            return _result(
                True,
                operation,
                "converted radial→linear",
                {
                    "gradient_id": gradient_id,
                    "gradient_units": _units(grad),
                    **{k: f"{v:g}" for k, v in coords.items()},
                },
                start,
            )

        if operation == "convert_to_radial":
            if grad.tag != f"{SVG}linearGradient":
                return _result(False, operation, "gradient is not linear", {}, start, "InvalidState")
            x1, y1, x2, y2 = (_num(grad.get(a)) for a in ("x1", "y1", "x2", "y2"))
            grad.tag = f"{SVG}radialGradient"
            for attr in ("x1", "y1", "x2", "y2"):
                grad.attrib.pop(attr, None)
            # cx/cy/r of 0.5 are objectBoundingBox fractions. Under userSpaceOnUse — which is
            # what Inkscape writes — they would place a half-pixel gradient at the document
            # origin, rendering the shape as a flat last-stop colour. Derive real geometry
            # from the line instead: centre = its midpoint, radius = half its length.
            if _user_space(grad) and None not in (x1, y1, x2, y2):
                dx, dy = x2 - x1, y2 - y1  # type: ignore[operator]
                coords = {
                    "cx": (x1 + x2) / 2,  # type: ignore[operator]
                    "cy": (y1 + y2) / 2,  # type: ignore[operator]
                    "r": ((dx * dx + dy * dy) ** 0.5) / 2,
                }
            else:
                coords = {"cx": 0.5, "cy": 0.5, "r": 0.5}
            for attr, value in coords.items():
                grad.set(attr, f"{value:g}")
            _write(tree, output_path)
            return _result(
                True,
                operation,
                "converted linear→radial",
                {
                    "gradient_id": gradient_id,
                    "gradient_units": _units(grad),
                    **{k: f"{v:g}" for k, v in coords.items()},
                },
                start,
            )

        return _result(False, operation, f"unknown operation: {operation}", {}, start, "ValueError")

    except Exception as e:
        return _result(False, operation, f"gradient op failed: {e}", {}, start, type(e).__name__)
