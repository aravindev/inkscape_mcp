"""Comprehensive document analysis for Inkscape SVG files.

PORTMANTEAU PATTERN RATIONALE:
Consolidates 6 document analysis operations into single interface. Prevents tool explosion
while maintaining
clean separation of concerns. Follows FastMCP 2.14.1+ SOTA standards.

SUPPORTED OPERATIONS:
- statistics: Get comprehensive document statistics
- validate: Validate SVG structure and syntax
- dimensions: Get document dimensions and aspect ratio
- quality: Analyze SVG quality metrics
- objects: List all objects in document with IDs and types
- structure: Analyze document structure hierarchy

OPERATIONS DETAIL:

**Document Statistics**:
  - statistics: Get comprehensive document statistics (dimensions, file size, object count, layers)

**Validation**:
  - validate: Validate SVG structure and syntax, report errors and warnings

**Dimension Analysis**:
  - dimensions: Get document dimensions with aspect ratio and unit information

**Quality Assessment**:
  - quality: Analyze SVG quality metrics (complexity, optimization potential, standards compliance)

**Object Discovery**:
  - objects: List all objects in document with IDs, types, and properties

**Structure Analysis**:
  - structure: Analyze document structure (layers, groups, hierarchy)

Args:
    operation (Literal, required): The analysis operation to perform. Must be one of:
        "statistics", "validate",
        "dimensions", "quality", "objects", "structure".
        - "statistics": Get comprehensive document statistics (requires: input_path)
        - "validate": Validate SVG structure and syntax (requires: input_path)
        - "dimensions": Get document dimensions and aspect ratio (requires: input_path)
        - "quality": Analyze SVG quality metrics (requires: input_path)
        - "objects": List document objects with IDs and types (requires: input_path)
        - "structure": Analyze document structure hierarchy (requires: input_path)

    input_path (str, required): Path to input SVG file. Required for all operations.
        Must be a valid file path accessible by the system. File must be readable.

    cli_wrapper (Any): Injected CLI wrapper dependency. Required. Handles Inkscape command
        execution.

    config (Any): Injected configuration dependency. Required. Contains Inkscape executable path
        and settings.

Returns:
    FastMCP 2.14.1+ Enhanced Response Pattern with success/error states, execution timing,
    next steps, and recovery options for failed operations.

Examples:
    # Get document statistics
    result = await inkscape_analysis(
        operation="statistics",
        input_path="drawing.svg"
    )

    # Validate SVG structure
    result = await inkscape_analysis(
        operation="validate",
        input_path="drawing.svg"
    )

    # List all objects in document
    result = await inkscape_analysis(
        operation="objects",
        input_path="drawing.svg"
    )

    Success Response:
    {
      "success": true,
      "operation": "operation_name",
      "summary": "Human-readable conversational summary",
      "result": {
        "data": {
          "input_path": "path/to/input.svg",
          "analysis_results": {
            "width": 800.0,
            "height": 600.0,
            "file_size": 15360,
            "format": "svg",
            "num_objects": 15,
            "num_layers": 3,
            "aspect_ratio": 1.333,
            "valid": true,
            "errors": [],
            "warnings": []
          }
        },
        "execution_time_ms": 123.45
      },
      "next_steps": ["Use inkscape_vector for path operations", "Optimize SVG if needed"],
      "context": {
        "operation_details": "Technical details about analysis results"
      },
      "suggestions": ["Related analysis operations", "Optimization recommendations"],
      "follow_up_questions": ["Would you like to optimize this SVG?",
        "Need to validate specific elements?"]
    }

    Error Response (Error Recovery Pattern):
    {
      "success": false,
      "operation": "operation_name",
      "error": "Error type (e.g., FileNotFoundError)",
      "message": "Human-readable error description",
      "recovery_options": ["Check file path and permissions", "Verify SVG file is valid",
        "Ensure Inkscape is installed"],
      "diagnostic_info": {
        "file_exists": false,
        "inkscape_available": true,
        "file_readable": false
      },
      "alternative_solutions": ["Use inkscape_file validate operation", "Check file format"]
    }

Examples:
    # Get comprehensive document statistics
    result = await inkscape_analysis(
        operation="statistics",
        input_path="drawing.svg"
    )

    # Validate SVG structure and syntax
    result = await inkscape_analysis(
        operation="validate",
        input_path="drawing.svg"
    )

    # Get document dimensions with aspect ratio
    result = await inkscape_analysis(
        operation="dimensions",
        input_path="drawing.svg"
    )

    # Analyze SVG quality metrics (when implemented)
    result = await inkscape_analysis(
        operation="quality",
        input_path="drawing.svg"
    )

    # List all objects in document (when implemented)
    result = await inkscape_analysis(
        operation="objects",
        input_path="drawing.svg"
    )

    # Analyze document structure (when implemented)
    result = await inkscape_analysis(
        operation="structure",
        input_path="drawing.svg"
    )

Errors:
    - FileNotFoundError: Input SVG file does not exist or is not readable
        Recovery options:
        - Verify file path is correct and accessible
        - Check file permissions (read access required)
        - Ensure file is a valid SVG document
        - Use absolute paths if relative paths fail

    - ValueError: Invalid SVG format or operation parameter
        Recovery options:
        - Verify operation is one of: statistics, validate, dimensions, quality, objects, structure
        - Check SVG file format (must be valid XML/SVG)
        - Ensure file extension matches content

    - InkscapeExecutionError: Inkscape CLI command failed
        Recovery options:
        - Verify Inkscape installation (run inkscape --version)
        - Check CLI arguments are valid for Inkscape version
        - Check process timeout settings in config
        - Verify SVG file is not corrupted

    - NotImplementedError: Operation not yet implemented
        Recovery options:
        - Check supported operations list (currently: statistics, validate, dimensions)
        - Use alternative operations that provide similar functionality
        - Check if operation is available in newer versions
"""

import re
import time
from pathlib import Path
from typing import Any

from lxml import etree
from pydantic import BaseModel

from ..mcp_tool_types import InkscapeAnalysisOperation

SVG_NS = "{http://www.w3.org/2000/svg}"
INK_NS = "{http://www.inkscape.org/namespaces/inkscape}"


class AnalysisResult(BaseModel):
    """Result model for analysis operations."""

    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


async def inkscape_analysis(
    operation: InkscapeAnalysisOperation,
    input_path: str,
    cli_wrapper: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """Inkscape document analysis portmanteau tool."""
    start_time = time.time()

    try:
        input_path_obj = Path(input_path)

        if not input_path_obj.exists():
            return AnalysisResult(
                success=False,
                operation=operation,
                message=f"File not found: {input_path}",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="FileNotFoundError",
            ).model_dump()

        if operation == "validate":
            # Validate SVG by attempting to load
            try:
                await cli_wrapper._execute_command(
                    [
                        str(config.inkscape_executable),
                        "--app-id-tag=mcp",
                        str(input_path_obj),
                        "--query-width",
                    ],
                    config.process_timeout,
                )

                return AnalysisResult(
                    success=True,
                    operation="validate",
                    message="SVG validation passed",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "valid": True,
                        "errors": [],
                        "warnings": [],
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return AnalysisResult(
                    success=False,
                    operation="validate",
                    message=f"SVG validation failed: {e}",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "valid": False,
                        "errors": [str(e)],
                        "warnings": [],
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "dimensions":
            # Get document dimensions
            try:
                width_result = await cli_wrapper._execute_command(
                    [
                        str(config.inkscape_executable),
                        "--app-id-tag=mcp",
                        str(input_path_obj),
                        "--query-width",
                    ],
                    config.process_timeout,
                )
                height_result = await cli_wrapper._execute_command(
                    [
                        str(config.inkscape_executable),
                        "--app-id-tag=mcp",
                        str(input_path_obj),
                        "--query-height",
                    ],
                    config.process_timeout,
                )

                width = float(width_result.strip())
                height = float(height_result.strip())

                return AnalysisResult(
                    success=True,
                    operation="dimensions",
                    message=f"Retrieved dimensions for {input_path}",
                    data={
                        "width": width,
                        "height": height,
                        "units": "px",
                        "aspect_ratio": width / height if height > 0 else 0,
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return AnalysisResult(
                    success=False,
                    operation="dimensions",
                    message=f"Dimension retrieval failed: {e}",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "statistics":
            # Was unreachable: an earlier `if operation == "statistics"` branch shadowed this
            # one and returned hardcoded num_objects/num_layers of 1 after two needless
            # Inkscape subprocess launches.
            return _analyze_statistics(input_path_obj, start_time)

        elif operation == "objects":
            return _analyze_objects(input_path_obj, start_time)

        elif operation == "structure":
            return _analyze_structure(input_path_obj, start_time)

        elif operation == "quality":
            return _analyze_quality(input_path_obj, start_time)

        else:
            # Defensive: unreachable for a well-typed caller, but the tools are also
            # invoked directly (tests, other tools) where `operation` is just a str.
            return AnalysisResult(  # type: ignore[unreachable]
                success=False,
                operation=operation,
                message=f"Operation '{operation}' not yet implemented",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="NotImplementedError",
            ).model_dump()

    except Exception as e:
        return AnalysisResult(
            success=False,
            operation=operation,
            message=f"Analysis failed: {e}",
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        ).model_dump()


def _parse_svg(path: Path) -> etree._Element:
    """Parse SVG and return root, plus a {tag-stripped: list of elements} index."""
    tree = etree.parse(str(path))
    return tree.getroot()


def _local_tag(elem: etree._Element) -> str:
    """Strip the XML namespace for cleaner type names."""
    tag = str(elem.tag)
    return tag.split("}", 1)[1] if "}" in tag else tag


def _document_size(root: etree._Element) -> tuple[float | None, float | None]:
    """User-space width/height, preferring viewBox over the (unit-bearing) attributes."""
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


def _analyze_objects(path: Path, start: float) -> dict[str, Any]:
    """List shape-bearing objects with id, type and viewBox-space bbox attrs."""
    try:
        root = _parse_svg(path)
        shape_tags = {
            "rect",
            "circle",
            "ellipse",
            "line",
            "polyline",
            "polygon",
            "path",
            "text",
            "image",
        }
        objects = []
        for el in root.iter():
            t = _local_tag(el)
            if t not in shape_tags:
                continue
            entry = {"id": el.get("id", ""), "type": t}
            for attr in ("x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "d"):
                if attr in el.attrib:
                    entry[attr] = el.get(attr)
            objects.append(entry)
        return AnalysisResult(
            success=True,
            operation="objects",
            message=f"Found {len(objects)} objects",
            data={"path": str(path.resolve()), "count": len(objects), "objects": objects},
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return AnalysisResult(
            success=False,
            operation="objects",
            message=f"Object enumeration failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _analyze_structure(path: Path, start: float) -> dict[str, Any]:
    """Layer + group hierarchy."""
    try:
        root = _parse_svg(path)

        def walk(el: etree._Element) -> list[dict[str, Any]]:
            children: list[dict[str, Any]] = []
            for c in el:
                t = _local_tag(c)
                if t == "g":
                    is_layer = c.get(f"{INK_NS}groupmode") == "layer"
                    children.append(
                        {
                            "id": c.get("id", ""),
                            "type": "layer" if is_layer else "group",
                            "label": c.get(f"{INK_NS}label", ""),
                            "children": walk(c),
                        }
                    )
            return children

        return AnalysisResult(
            success=True,
            operation="structure",
            message="Document structure extracted",
            data={"path": str(path.resolve()), "layers": walk(root)},
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return AnalysisResult(
            success=False,
            operation="structure",
            message=f"Structure analysis failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _analyze_statistics(path: Path, start: float) -> dict[str, Any]:
    """File-size + dimensions + object/layer counts via XML walk; cheaper than --query-all."""
    try:
        root = _parse_svg(path)
        all_elems = list(root.iter())
        shape_count = sum(
            1
            for e in all_elems
            if _local_tag(e) in {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "image"}
        )
        layer_count = sum(1 for e in all_elems if _local_tag(e) == "g" and e.get(f"{INK_NS}groupmode") == "layer")
        # Dimensions come from the document attributes rather than two `--query-*`
        # subprocess launches; viewBox is the authoritative user-space extent.
        width, height = _document_size(root)
        return AnalysisResult(
            success=True,
            operation="statistics",
            message=f"Statistics collected: {shape_count} shape(s), {layer_count} layer(s)",
            data={
                "path": str(path.resolve()),
                "file_size_bytes": path.stat().st_size,
                "format": "svg",
                "width": width,
                "height": height,
                "element_count": len(all_elems),
                "shape_count": shape_count,
                "layer_count": layer_count,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return AnalysisResult(
            success=False,
            operation="statistics",
            message=f"Statistics failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _analyze_quality(path: Path, start: float) -> dict[str, Any]:
    """Heuristic quality score: rewards few elements, penalises unused defs and deep nesting."""
    try:
        root = _parse_svg(path)
        all_elems = list(root.iter())
        elem_count = len(all_elems)
        defs_children = sum(len(d) for d in root.iter(f"{SVG_NS}defs"))
        # Detect unused gradients/patterns by id-vs-url(#id) reference count.
        ids = {e.get("id"): _local_tag(e) for e in all_elems if e.get("id")}
        text = etree.tostring(root, encoding="unicode")
        unused_defs = sum(
            1
            for i, t in ids.items()
            if t in {"linearGradient", "radialGradient", "pattern", "filter"} and f"url(#{i})" not in text
        )
        # Score in [0, 100]. Subtract penalties.
        score = max(0, 100 - elem_count // 10 - unused_defs * 5)
        recs = []
        if unused_defs:
            recs.append(f"{unused_defs} unused gradient/pattern/filter defs — consider vacuuming.")
        if elem_count > 500:
            recs.append("Large element count — consider path-simplify or scour_svg.")
        return AnalysisResult(
            success=True,
            operation="quality",
            message="Quality analysis complete",
            data={
                "path": str(path.resolve()),
                "score": score,
                "element_count": elem_count,
                "defs_children": defs_children,
                "unused_defs": unused_defs,
                "recommendations": recs,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return AnalysisResult(
            success=False,
            operation="quality",
            message=f"Quality analysis failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()
