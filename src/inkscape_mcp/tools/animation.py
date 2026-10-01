"""SVG animation: SMIL and CSS keyframes, applied to elements of an existing document.

Operations: list_presets, apply_preset, animate_attribute, animate_transform, animate_motion,
animate_color, css_animation, list_animations, remove_animation.

The operation set and the preset catalogue (bounce, fade in/out, slide, rotate, pulse, shake) come
from sandraschi/inkscape-mcp (MIT); see NOTICE.md. What differs, and why:

* **Every operation targets an element of your file** (``input_path`` + ``target_id``). There, only
  ``animate_element`` touched an existing document; the rest always generated a new demo circle or
  rectangle. A standalone demo is still available: leave ``input_path`` empty for ``apply_preset``.
* **Built with an XML tree, never string splicing.** Values and names cannot break out of their
  attribute, and names are validated.
* ``animateTransform`` uses ``additive="sum"`` so an element's own ``transform`` survives instead of
  being replaced, and ``calcMode="spline"`` is only emitted together with the ``keySplines`` it needs.
* Presets that pivot (rotate, pulse) use the element's real centre, from its geometry or an explicit
  ``cx``/``cy``, instead of a fixed point.

SMIL and CSS animations run in browsers and most SVG viewers; Inkscape itself does not play them.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

from lxml import etree
from pydantic import BaseModel

from ..security import atomic_output
from ._svg_io import parse_svg, write_tree

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_SVG = f"{{{SVG_NS}}}"
_HREF = f"{{{XLINK_NS}}}href"

OPERATIONS = (
    "list_presets",
    "apply_preset",
    "animate_attribute",
    "animate_transform",
    "animate_motion",
    "animate_color",
    "css_animation",
    "list_animations",
    "remove_animation",
)
PRESETS = ("bounce", "fade_in", "fade_out", "slide", "rotate", "pulse", "shake")
_TRANSFORM_TYPES = ("translate", "scale", "rotate", "skewX", "skewY")
_SMIL_TAGS = ("animate", "animateTransform", "animateMotion", "animateColor", "set")

_NAME_RE = re.compile(r"^[A-Za-z_][\w.:-]*$")
_CSS_IDENT_RE = re.compile(r"^[A-Za-z_][\w-]*$")
_REPEAT_RE = re.compile(r"^(indefinite|\d+(\.\d+)?)$")
_NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_SIMPLE_VALUE_RE = re.compile(r"^[\w\s#%.,;:()+\-/]*$")  # numbers, colours, units, lists; no markup


class AnimationResult(BaseModel):
    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


class _AnimError(Exception):
    """A user-facing problem with the request, not a bug."""


# ---------------------------------------------------------------------------- validation


def _name(value: str, what: str) -> str:
    if not value or not _NAME_RE.match(value):
        raise _AnimError(f"{what} {value!r} is not a valid name")
    return value


def _css_ident(value: str, what: str) -> str:
    if not value or not _CSS_IDENT_RE.match(value):
        raise _AnimError(f"{what} {value!r} must be a CSS identifier (letters, digits, '_' and '-')")
    return value


def _seconds(duration: float) -> str:
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise _AnimError("duration must be a positive number of seconds")
    return f"{duration:g}s"


def _repeat(value: str) -> str:
    if not _REPEAT_RE.match(value):
        raise _AnimError("repeat must be 'indefinite' or a number")
    return value


_MAX_TEXT = 10_000


def _values(value: str, what: str = "values") -> str:
    if not value or len(value) > _MAX_TEXT or not _SIMPLE_VALUE_RE.match(value):
        raise _AnimError(f"{what} must be a ';'-separated list of numbers, colours or lengths (no markup)")
    return value


def _value_list(value: str, what: str = "values") -> str:
    """Like :func:`_values` but SMIL needs at least a start and an end value."""
    cleaned = _values(value, what)
    if len([v for v in cleaned.split(";") if v.strip()]) < 2:
        raise _AnimError(f"{what} needs at least two ';'-separated entries (start;end)")
    return cleaned


def _fill_mode(value: str) -> str:
    if value not in ("freeze", "remove"):
        raise _AnimError("fill_mode must be 'freeze' or 'remove'")
    return value


# ---------------------------------------------------------------------------- element helpers


def _find(root: etree._Element, target_id: str) -> etree._Element:
    if not target_id:
        raise _AnimError("target_id is required")
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("id") == target_id:
            return el
    raise _AnimError(f"element {target_id!r} not found")


def _local(el: etree._Element) -> str:
    return str(etree.QName(el).localname)


def _f(el: etree._Element, attr: str, default: float = 0.0) -> float:
    try:
        return float(re.match(_NUM, (el.get(attr) or "").strip()).group(0))  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        return default


def _center(el: etree._Element, cx: float | None, cy: float | None) -> tuple[float, float]:
    """Pivot point in the element's own coordinate system, or a clear error."""
    if cx is not None and cy is not None:
        return cx, cy
    tag = _local(el)
    if tag in ("circle", "ellipse"):
        return _f(el, "cx"), _f(el, "cy")
    if tag in ("rect", "image", "use", "foreignObject", "svg"):
        return _f(el, "x") + _f(el, "width") / 2, _f(el, "y") + _f(el, "height") / 2
    if tag == "line":
        return (_f(el, "x1") + _f(el, "x2")) / 2, (_f(el, "y1") + _f(el, "y2")) / 2
    if tag in ("polygon", "polyline"):
        pts = [float(n) for n in re.findall(_NUM, el.get("points") or "")]
        xs, ys = pts[0::2], pts[1::2]
        if xs and ys:
            return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    raise _AnimError(
        f"cannot find the centre of <{tag}>; pass cx and cy (in the element's own coordinates) for this preset"
    )


def _smil(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    node = etree.SubElement(parent, f"{_SVG}{tag}")
    for k, v in attrs.items():
        if v != "":
            node.set(k, v)
    return node


def _timing(
    duration: float, repeat: str, fill_mode: str, key_times: str, key_splines: str, values_count: int
) -> dict[str, str]:
    out = {"dur": _seconds(duration), "repeatCount": _repeat(repeat), "fill": _fill_mode(fill_mode)}
    if key_times:
        out["keyTimes"] = _values(key_times, "key_times")
        if len(out["keyTimes"].split(";")) != values_count:
            raise _AnimError("key_times must have exactly one entry per value")
    if key_splines:
        out["keySplines"] = _values(key_splines, "key_splines")
        if not key_times:
            raise _AnimError("key_splines needs key_times")
        if len(out["keySplines"].split(";")) != values_count - 1:
            raise _AnimError("key_splines needs one entry per interval (values - 1)")
        out["calcMode"] = "spline"  # only valid together with keySplines
    return out


# ---------------------------------------------------------------------------- presets


def _preset_nodes(
    el: etree._Element, name: str, duration: float, repeat: str, amplitude: float, cx: float | None, cy: float | None
) -> list[etree._Element]:
    """Build the animation children for preset ``name`` (not yet attached)."""
    holder = etree.Element("holder")
    dur = _seconds(duration)
    ease = {"calcMode": "spline", "keyTimes": "0;0.5;1", "keySplines": "0.33 0 0.66 1;0.33 0 0.66 1"}

    if name in ("fade_in", "fade_out"):
        a, b = ("0", "1") if name == "fade_in" else ("1", "0")
        _smil(holder, "animate", attributeName="opacity", **{"from": a, "to": b}, dur=dur, fill="freeze")
    elif name == "bounce":
        _smil(
            holder,
            "animateTransform",
            attributeName="transform",
            type="translate",
            values=f"0 0;0 {-amplitude:g};0 0",
            dur=dur,
            repeatCount=_repeat(repeat),
            additive="sum",
            **ease,
        )
    elif name == "slide":
        _smil(
            holder,
            "animateTransform",
            attributeName="transform",
            type="translate",
            values=f"{-amplitude:g} 0;0 0",
            dur=dur,
            fill="freeze",
            additive="sum",
            calcMode="spline",
            keyTimes="0;1",
            keySplines="0.25 0.1 0.25 1",
        )
    elif name == "shake":
        steps = [amplitude * math.sin(i * math.pi / 2) for i in range(0, 9)]
        vals = ";".join(f"{v:.2f} 0" for v in steps)
        _smil(
            holder,
            "animateTransform",
            attributeName="transform",
            type="translate",
            values=vals,
            dur=dur,
            repeatCount=_repeat(repeat),
            additive="sum",
        )
    elif name == "rotate":
        x, y = _center(el, cx, cy)
        _smil(
            holder,
            "animateTransform",
            attributeName="transform",
            type="rotate",
            **{"from": f"0 {x:g} {y:g}", "to": f"360 {x:g} {y:g}"},
            dur=dur,
            repeatCount=_repeat(repeat),
            additive="sum",
        )
    elif name == "pulse":
        # Scaling about the centre = translate(c*(1-s)) then scale(s); animate both in lockstep.
        x, y = _center(el, cx, cy)
        scales = (1.0, 1.0 + amplitude / 100.0, 1.0)
        common = {"attributeName": "transform", "dur": dur, "repeatCount": _repeat(repeat), "additive": "sum", **ease}
        _smil(
            holder,
            "animateTransform",
            type="translate",
            values=";".join(f"{x * (1 - s):g} {y * (1 - s):g}" for s in scales),
            **common,
        )
        _smil(holder, "animateTransform", type="scale", values=";".join(f"{s:g}" for s in scales), **common)
        _smil(holder, "animate", attributeName="opacity", values="1;0.6;1", dur=dur, repeatCount=_repeat(repeat))
    else:
        raise _AnimError(f"unknown preset {name!r}; one of {', '.join(PRESETS)}")
    return list(holder)


def _standalone_demo(
    width: int, height: int, x: float, y: float, r: float, fill: str
) -> tuple[etree._ElementTree, str]:
    """A fresh document holding one circle to animate, for trying presets without a file."""
    if not (0 < width <= 20000 and 0 < height <= 20000):
        raise _AnimError("width and height must be between 1 and 20000")
    root = etree.Element(f"{_SVG}svg", nsmap={None: SVG_NS, "xlink": XLINK_NS})
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("viewBox", f"0 0 {width} {height}")
    circle = etree.SubElement(root, f"{_SVG}circle")
    circle.set("id", "demo")
    circle.set("cx", f"{x:g}")
    circle.set("cy", f"{y:g}")
    circle.set("r", f"{max(r, 1):g}")
    circle.set("fill", _values(fill, "fill"))
    return etree.ElementTree(root), "demo"


# ---------------------------------------------------------------------------- entry point


async def inkscape_animation(
    operation: str,
    input_path: str = "",
    output_path: str = "",
    target_id: str = "",
    preset_name: str = "",
    attribute: str = "",
    values: str = "",
    key_times: str = "",
    key_splines: str = "",
    transform_type: str = "rotate",
    path_data: str = "",
    path_id: str = "",
    rotate_auto: bool = False,
    color_from: str = "",
    color_to: str = "",
    animation_name: str = "",
    css_keyframes: str = "",
    duration: float = 1.0,
    repeat: str = "indefinite",
    fill_mode: str = "freeze",
    amplitude: float = 40.0,
    cx: float | None = None,
    cy: float | None = None,
    x: float = 400,
    y: float = 300,
    r: float = 50,
    fill: str = "#4488ff",
    width: int = 800,
    height: int = 600,
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Add, list or remove SMIL/CSS animations on elements of an SVG file."""
    start = time.time()

    def result(ok: bool, message: str, data: dict[str, Any] | None = None, error: str = "") -> dict[str, Any]:
        return AnimationResult(
            success=ok,
            operation=operation,
            message=message,
            data=data or {},
            execution_time_ms=(time.time() - start) * 1000,
            error=error,
        ).model_dump()

    if operation not in OPERATIONS:
        return result(False, f"unknown operation {operation!r}; one of {', '.join(OPERATIONS)}", error="ValueError")
    if operation == "list_presets":
        return result(True, f"{len(PRESETS)} presets", {"presets": list(PRESETS)})

    try:
        standalone = not input_path
        if standalone:
            if operation != "apply_preset":
                raise _AnimError("input_path is required (only apply_preset can build a standalone demo)")
            if not output_path:
                raise _AnimError("output_path is required for a standalone demo")
            tree, target_id = _standalone_demo(width, height, x, y, r, fill)
        else:
            tree = parse_svg(input_path)
        root = tree.getroot()

        if operation == "list_animations":
            scope = _find(root, target_id) if target_id else root
            found = []
            for node in scope.iter():
                if isinstance(node.tag, str) and _local(node) in _SMIL_TAGS:
                    parent = node.getparent()
                    found.append(
                        {
                            "element": parent.get("id") if parent is not None else None,
                            "kind": _local(node),
                            "attribute": node.get("attributeName"),
                            "dur": node.get("dur"),
                        }
                    )
            return result(True, f"{len(found)} animation(s)", {"animations": found, "count": len(found)})

        el = _find(root, target_id)
        added: list[str] = []

        if operation == "remove_animation":
            doomed = [c for c in el if isinstance(c.tag, str) and _local(c) in _SMIL_TAGS]
            for c in doomed:
                el.remove(c)
            added = [f"removed {len(doomed)}"]
            summary = f"removed {len(doomed)} animation(s) from {target_id!r}"

        elif operation == "apply_preset":
            nodes = _preset_nodes(
                el, _name(preset_name, "preset_name") if preset_name else "", duration, repeat, amplitude, cx, cy
            )
            for n in nodes:
                el.append(n)
            added = [_local(n) for n in nodes]
            summary = f"applied preset {preset_name!r} to {target_id!r}"

        elif operation == "animate_attribute":
            vals = _value_list(values)
            n = len(vals.split(";"))
            node = _smil(
                el,
                "animate",
                attributeName=_name(attribute, "attribute"),
                values=vals,
                **_timing(duration, repeat, fill_mode, key_times, key_splines, n),
            )
            added, summary = [_local(node)], f"animating {attribute!r} on {target_id!r}"

        elif operation == "animate_transform":
            if transform_type not in _TRANSFORM_TYPES:
                raise _AnimError(f"transform_type must be one of {', '.join(_TRANSFORM_TYPES)}")
            vals = _value_list(values)
            node = _smil(
                el,
                "animateTransform",
                attributeName="transform",
                type=transform_type,
                values=vals,
                additive="sum",  # keep the element's own transform
                **_timing(duration, repeat, fill_mode, key_times, key_splines, len(vals.split(";"))),
            )
            added, summary = [_local(node)], f"animating {transform_type} on {target_id!r}"

        elif operation == "animate_motion":
            node = _smil(
                el,
                "animateMotion",
                dur=_seconds(duration),
                repeatCount=_repeat(repeat),
                fill=_fill_mode(fill_mode),
                rotate="auto" if rotate_auto else "",
            )
            if path_id:
                _find(root, path_id)  # must exist
                mpath = etree.SubElement(node, f"{_SVG}mpath")
                mpath.set(_HREF, f"#{_name(path_id, 'path_id')}")
            elif path_data:
                if len(path_data) > _MAX_TEXT or not re.match(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE\s,.+\-]+$", path_data):
                    raise _AnimError("path_data must be SVG path data (e.g. 'M 0,0 C 50,0 50,100 100,100')")
                node.set("path", path_data)
            else:
                raise _AnimError("give either path_data (an SVG path 'd' string) or path_id (an existing path)")
            added, summary = [_local(node)], f"animating {target_id!r} along a path"

        elif operation == "animate_color":
            prop = _name(attribute or "fill", "attribute")
            if not color_to:
                raise _AnimError("color_to is required")
            start_color = color_from or el.get(prop) or "#000000"
            vals = f"{_values(start_color, 'color_from')};{_values(color_to, 'color_to')};{start_color}"
            node = _smil(
                el, "animate", attributeName=prop, values=vals, dur=_seconds(duration), repeatCount=_repeat(repeat)
            )
            added, summary = [_local(node)], f"animating {prop!r} colour on {target_id!r}"

        elif operation == "css_animation":
            cls = _css_ident(animation_name, "animation_name")
            body = css_keyframes.strip()
            if (
                not body
                or len(body) > _MAX_TEXT
                or any(ch in body for ch in "<>")
                or "@import" in body.lower()
                or "url(" in body.lower()
            ):
                raise _AnimError("css_keyframes must be plain keyframe rules (e.g. 'from{opacity:0} to{opacity:1}')")
            style = root.find(f"{_SVG}style")
            if style is None:
                style = etree.Element(f"{_SVG}style")
                root.insert(0, style)
            iteration = "infinite" if repeat == "indefinite" else _repeat(repeat)
            style.text = (style.text or "") + (
                f"\n@keyframes {cls} {{ {body} }}\n.{cls} {{ animation: {cls} {_seconds(duration)} {iteration}; }}\n"
            )
            classes = (el.get("class") or "").split()
            if cls not in classes:
                el.set("class", " ".join([*classes, cls]))
            added, summary = ["style"], f"CSS animation {cls!r} on {target_id!r}"

        else:  # unreachable: operation validated above
            raise _AnimError(f"unsupported operation {operation!r}")

        out = output_path or input_path
        with atomic_output(out) as tmp:
            write_tree(tree, str(tmp))
        return result(
            True, summary, {"target_id": target_id, "added": added, "output_path": out, "standalone": standalone}
        )

    except _AnimError as exc:
        return result(False, str(exc), error="ValueError")
    except (OSError, etree.XMLSyntaxError) as exc:
        return result(False, f"cannot read or write SVG: {exc}", error=type(exc).__name__)
    except Exception as exc:
        return result(False, f"animation failed: {exc}", error=type(exc).__name__)
