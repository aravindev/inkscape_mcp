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


def _find_gradient(root: etree._Element, gradient_id: str) -> etree._Element | None:
    for tag in ("linearGradient", "radialGradient"):
        for el in root.iter(f"{SVG}{tag}"):
            if el.get("id") == gradient_id:
                return el
    return None


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

        if operation == "list_stops":
            grad = _find_gradient(root, gradient_id)
            if grad is None:
                return _result(False, operation, f"gradient '{gradient_id}' not found", {}, start, "NotFound")
            stops = []
            for s in _stops(grad):
                stops.append(
                    {
                        "id": s.get("id", ""),
                        "offset": s.get("offset", ""),
                        **_stop_color_opacity(s),
                    }
                )
            return _result(
                True,
                operation,
                f"found {len(stops)} stops",
                {"gradient_id": gradient_id, "stops": stops},
                start,
            )

        grad = _find_gradient(root, gradient_id)
        if grad is None and operation in {
            "add_stop",
            "remove_stop",
            "set_stop_color",
            "convert_to_linear",
            "convert_to_radial",
        }:
            return _result(False, operation, f"gradient '{gradient_id}' not found", {}, start, "NotFound")

        if operation == "add_stop":
            target = _parse_offset(stop_offset)
            new_stop = etree.SubElement(grad, f"{SVG}stop")
            new_stop.set("offset", _format_offset_pct(target))
            _set_stop_color(new_stop, stop_color or "#000000")
            new_stop.set("stop-opacity", f"{stop_opacity:g}")
            # Sort stops by offset so the gradient renders monotonically.
            sorted_stops = sorted(_stops(grad), key=lambda s: _parse_offset(s.get("offset", "0")))
            for s in _stops(grad):
                grad.remove(s)
            for s in sorted_stops:
                grad.append(s)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"added stop at {target * 100:g}%",
                {"gradient_id": gradient_id, "offset": target},
                start,
            )

        if operation == "remove_stop":
            target = _parse_offset(stop_offset)
            stops = _stops(grad)
            if not stops:
                return _result(False, operation, "no stops to remove", {}, start, "NotFound")
            closest = min(stops, key=lambda s: abs(_parse_offset(s.get("offset", "0")) - target))
            grad.remove(closest)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"removed stop near {target * 100:g}%",
                {"gradient_id": gradient_id},
                start,
            )

        if operation == "set_stop_color":
            target = _parse_offset(stop_offset)
            stops = _stops(grad)
            if not stops:
                return _result(False, operation, "no stops to recolor", {}, start, "NotFound")
            match = min(stops, key=lambda s: abs(_parse_offset(s.get("offset", "0")) - target))
            _set_stop_color(match, stop_color or "#000000")
            _write(tree, output_path)
            return _result(
                True,
                operation,
                f"recoloured stop near {target * 100:g}% to {stop_color}",
                {"gradient_id": gradient_id, "stop_color": stop_color},
                start,
            )

        if operation == "convert_to_linear":
            if grad.tag != f"{SVG}radialGradient":
                return _result(False, operation, "gradient is not radial", {}, start, "InvalidState")
            grad.tag = f"{SVG}linearGradient"
            for attr in ("cx", "cy", "r", "fx", "fy"):
                if attr in grad.attrib:
                    del grad.attrib[attr]
            for attr, default in (("x1", "0"), ("y1", "0"), ("x2", "1"), ("y2", "0")):
                if attr not in grad.attrib:
                    grad.set(attr, default)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                "converted radial→linear",
                {"gradient_id": gradient_id},
                start,
            )

        if operation == "convert_to_radial":
            if grad.tag != f"{SVG}linearGradient":
                return _result(False, operation, "gradient is not linear", {}, start, "InvalidState")
            grad.tag = f"{SVG}radialGradient"
            for attr in ("x1", "y1", "x2", "y2"):
                if attr in grad.attrib:
                    del grad.attrib[attr]
            for attr, default in (("cx", "0.5"), ("cy", "0.5"), ("r", "0.5")):
                if attr not in grad.attrib:
                    grad.set(attr, default)
            _write(tree, output_path)
            return _result(
                True,
                operation,
                "converted linear→radial",
                {"gradient_id": gradient_id},
                start,
            )

        return _result(False, operation, f"unknown operation: {operation}", {}, start, "ValueError")

    except Exception as e:
        return _result(False, operation, f"gradient op failed: {e}", {}, start, type(e).__name__)
