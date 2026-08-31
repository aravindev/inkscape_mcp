"""One definition of "how big is this document", shared by every reporting site.

Four call sites used to report `width`/`height` and mean two different things:
`analysis statistics` returned the page size, while `analysis dimensions`, `file info`
and `vector query_document` shelled out to `--query-width`, which is the drawing's
bounding box. Same field names, no labels, and no way for a caller to tell which one it
had — on a 400x300 page holding a 220x150 drawing, half the tools said 400x300 and half
said 220x150.

Both numbers are legitimately useful, so both are reported under names that say which is
which. `width`/`height` remain as deprecated aliases of the page size so existing callers
keep working for one release.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lxml import etree


def page_size(path: str | Path) -> tuple[float | None, float | None]:
    """The page (canvas) size in user units, preferring viewBox over width/height.

    viewBox wins because `width`/`height` may carry a physical unit (`400mm`) whose
    numeric part is not the user-space size.
    """
    try:
        root = etree.parse(str(path)).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None, None

    viewbox = root.get("viewBox")
    if viewbox:
        parts = [p for p in re.split(r"[ ,]+", viewbox.strip()) if p]
        if len(parts) >= 4:
            try:
                return float(parts[2]), float(parts[3])
            except ValueError:
                pass

    def _num(raw: str | None) -> float | None:
        m = re.match(r"\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)", raw or "")
        return float(m.group(1)) if m else None

    return _num(root.get("width")), _num(root.get("height"))


async def drawing_size(path: str | Path, cli_wrapper: Any, config: Any) -> tuple[float | None, float | None]:
    """The drawing's bounding box, via Inkscape's `--query-width` / `--query-height`.

    This is the extent of the ink, which can be smaller than the page (a small drawing
    on a big canvas) or larger (content overflowing the page).
    """
    try:
        raw_w = await cli_wrapper._execute_command(
            [str(config.inkscape_executable), "--app-id-tag=mcp", str(path), "--query-width"],
            config.process_timeout,
        )
        raw_h = await cli_wrapper._execute_command(
            [str(config.inkscape_executable), "--app-id-tag=mcp", str(path), "--query-height"],
            config.process_timeout,
        )
        return float(raw_w.strip()), float(raw_h.strip())
    except (ValueError, OSError, RuntimeError):
        return None, None


async def size_report(path: str | Path, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """The block every dimension-reporting operation merges into its `data`."""
    page_w, page_h = page_size(path)
    draw_w, draw_h = await drawing_size(path, cli_wrapper, config)

    report: dict[str, Any] = {
        "page_width": page_w,
        "page_height": page_h,
        "drawing_width": draw_w,
        "drawing_height": draw_h,
        # Deprecated aliases — kept for one release, now consistently the PAGE size.
        "width": page_w,
        "height": page_h,
    }
    if page_w and page_h:
        report["aspect_ratio"] = page_w / page_h
    return report
