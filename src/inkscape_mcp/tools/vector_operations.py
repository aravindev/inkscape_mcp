"""Advanced vector operations for Inkscape SVG documents.

PORTMANTEAU PATTERN RATIONALE:
Consolidates every advanced vector operation into a single interface. Prevents tool explosion
while maintaining full functionality and improving discoverability. The authoritative
operation list is the ``InkscapeVectorOperation`` Literal in ``mcp_tool_types``; counts
advertised to clients derive from it via ``OPERATION_COUNTS`` rather than being restated here.

SUPPORTED OPERATIONS:
- trace_image: Convert raster images to vector paths
- generate_barcode_qr: Generate QR codes and barcodes as SVG elements
- apply_boolean: Boolean operations (union, difference, intersection, exclusion)
- measure_object: Query object dimensions and bounding box
- optimize_svg: Clean and optimize SVG structure
- render_preview: Generate PNG preview at specified DPI
- path_operations: Path manipulation (simplify, clean, combine, break_apart)
- text_to_path: Convert text elements to editable vector paths
- export_dxf: Export to CAD format (DXF)
- layers_to_files: Export layers as separate files
- fit_canvas_to_drawing: Resize canvas to match drawing bounds
- object_raise: Raise object in Z-order
- object_lower: Lower object in Z-order
- set_document_units: Normalize document coordinate systems
- generate_laser_dot: Create animated laser pointer dot

OPERATIONS DETAIL:

**Raster-to-Vector Conversion**:
  - trace_image: Convert raster images to vector paths using potrace algorithm

**Code Generation**:
  - generate_barcode_qr: Generate QR codes and barcodes as SVG elements
  - generate_laser_dot: Create animated laser pointer dot for presentations

**Path Manipulation**:
  - path_operations: Path manipulation (simplify, clean, combine, break_apart, inset/outset)
  - apply_boolean: Boolean operations (union, difference, intersection, exclusion)

**Object Operations**:
  - object_to_path: Convert shapes (rectangles, circles, etc.) to editable paths
  - object_raise: Raise object in Z-order (move up in layer stack)
  - object_lower: Lower object in Z-order (move down in layer stack)

**Text Operations**:
  - text_to_path: Convert text elements to editable vector paths

**Document Operations**:
  - query_document: Get document statistics (dimensions, object count)
  - measure_object: Query object dimensions and bounding box
  - count_nodes: Count path nodes for complexity analysis
  - fit_canvas_to_drawing: Resize canvas to match drawing bounds
  - set_document_units: Normalize document coordinate systems (px, mm, in)

**Export & Rendering**:
  - render_preview: Generate PNG preview at specified DPI
  - export_dxf: Export to CAD format (DXF)
  - layers_to_files: Export layers as separate files

**Optimization**:
  - optimize_svg: Clean and optimize SVG structure
  - scour_svg: Remove metadata and unnecessary elements

Args:
    operation (Literal, required): The vector operation to perform. Must be one of:
        "trace_image", "generate_barcode_qr",
        "apply_boolean", "measure_object", "optimize_svg", "render_preview", "path_operations",
        "text_to_path",
        "export_dxf", "layers_to_files", "fit_canvas_to_drawing", "object_raise", "object_lower",
        "set_document_units",
        "generate_laser_dot".

    input_path (str | None): Path to input SVG file. Required for most operations.
        Must be a valid file path accessible by the system.

    output_path (str | None): Path for output file. Required for export/optimization operations.
        Directory must exist and be writable.

    object_id (str | None): Unique identifier for SVG object. Required for: measure_object,
        object_raise, object_lower.
        Must match an existing object ID in the SVG document.

    boolean_type (str | None): Type of boolean operation. Must be one of: "union", "difference",
        "intersection", "exclusion".
        Required for: apply_boolean operation.

    barcode_data (str | None): Data to encode in barcode/QR. Required for:
        generate_barcode_qr operation.

    optimization_type (str | None): Type of optimization. Must be one of: "simplify", "scour",
        "clean".
        Required for: optimize_svg operation.

    path_operation (str | None): Type of path operation. Must be one of: "simplify", "clean",
        "combine", "break_apart", "inset", "outset".
        Required for: path_operations operation.

    units (str | None): Document units for normalization. Must be one of: "px", "mm", "in",
        "pt", "pc".
        Required for: set_document_units operation.

    cli_wrapper (Any): Injected CLI wrapper dependency. Required. Handles Inkscape command
        execution.

    config (Any): Injected configuration dependency. Required. Contains Inkscape executable path
        and settings.

Returns:
    FastMCP 2.14.1+ Enhanced Response Pattern with success/error states, execution timing,
    next steps, and recovery options for failed operations.

Examples:
    # Convert bitmap to vector paths
    result = await inkscape_vector(
        operation="trace_image",
        input_path="bitmap.png",
        output_path="vector.svg"
    )

    # Apply boolean union operation
    result = await inkscape_vector(
        operation="apply_boolean",
        boolean_type="union",
        input_path="shapes.svg",
        output_path="combined.svg"
    )

    # Measure object dimensions
    result = await inkscape_vector(
        operation="measure_object",
        input_path="drawing.svg",
        object_id="rect1"
    )

PREREQUISITES:
- Requires an Inkscape 1.4.x CLI installation (the supported line; Actions API)
- For boolean operations: Requires object IDs or select_all parameter
- For path operations: Requires valid SVG path elements

Args:
    operation (Literal, required): The vector operation to perform. Must be one of:
        "trace_image", "generate_barcode_qr", "generate_laser_dot", "apply_boolean",
        "path_simplify", "path_clean", "path_combine", "path_break_apart",
        "object_to_path", "object_raise", "object_lower", "measure_object",
        "query_document", "count_nodes", "render_preview", "set_document_units".

    input_path (str | None): Path to input SVG file. Required for most operations.
        Must be a valid SVG file accessible by the system.

    output_path (str | None): Path for output file. Required for operations that modify files.
        Directory must exist and be writable. Required for: trace_image, apply_boolean,
        path_simplify, path_clean, object_raise, object_lower, render_preview, set_document_units.

    object_id (str | None): Target object ID within SVG document. Required for:
        measure_object, count_nodes, path_simplify, object_raise, object_lower.
        Object ID must exist in the SVG document.

    object_ids (list[str] | None): List of object IDs for multi-object operations.
        Required for: apply_boolean (when select_all=False). Must contain at least 2 IDs.

    select_all (bool): Select all objects for operation. Required for: apply_boolean
        (when object_ids not provided). Default: False.

    operation_type (str | None): Type of boolean operation. Required for: apply_boolean.
        Must be one of: "union", "difference", "intersection", "exclusion".

    barcode_data (str | None): Data to encode in QR code or barcode. Required for:
        generate_barcode_qr.

    threshold (float): Simplification threshold for path_simplify. Default: 1.0.
        Higher values result in more aggressive simplification.

    dpi (int): DPI for render_preview operation. Default: 96. Higher values produce
        higher resolution previews but take longer to render.

    units (str | None): Document units for set_document_units. Must be one of:
        "px", "mm", "in", "pt", "cm". Default: "px".

    x (float): X coordinate for generate_laser_dot. Default: 300.

    y (float): Y coordinate for generate_laser_dot. Default: 200.

    cli_wrapper (Any): Injected CLI wrapper dependency. Required. Handles Inkscape command execution.

    config (Any): Injected configuration dependency. Required. Contains Inkscape executable path
        and settings.

Returns:
    FastMCP 2.14.1+ Enhanced Response Pattern (Structured Returns):

    Success Response:
    {
      "success": true,
      "operation": "operation_name",
      "summary": "Human-readable conversational summary",
      "result": {
        "data": {
          "input_path": "path/to/input.svg",
          "output_path": "path/to/output.svg",
          "operation_result": {
            "object_id": "circle1",
            "width": 100.0,
            "height": 100.0,
            "x": 50.0,
            "y": 50.0
          }
        },
        "execution_time_ms": 123.45
      },
      "next_steps": ["Suggested next operations"],
      "context": {
        "operation_details": "Technical details about vector operation"
      },
      "suggestions": ["Related vector operations"],
      "follow_up_questions": ["Questions about operation parameters"]
    }

    Error Response (Error Recovery Pattern):
    {
      "success": false,
      "operation": "operation_name",
      "error": "Error type (e.g., ValueError)",
      "message": "Human-readable error description",
      "recovery_options": ["Provide object_ids or set select_all=true",
        "Verify object IDs exist in document"],
      "diagnostic_info": {
        "object_ids_provided": false,
        "select_all": false,
        "valid_operation_types": ["union", "difference", "intersection", "exclusion"]
      },
      "alternative_solutions": ["Use query_document to list available object IDs",
        "Use select_all=true for all objects"]
    }

Examples:
    # Trace bitmap image to vector paths
    result = await inkscape_vector(
        operation="trace_image",
        input_path="sketch.png",
        output_path="vector.svg"
    )

    # Generate QR code
    result = await inkscape_vector(
        operation="generate_barcode_qr",
        barcode_data="https://example.com",
        output_path="qr.svg"
    )

    # Apply boolean union to specific objects
    result = await inkscape_vector(
        operation="apply_boolean",
        input_path="shapes.svg",
        output_path="union.svg",
        operation_type="union",
        object_ids=["shape1", "shape2"]
    )

    # Apply boolean union to all objects
    result = await inkscape_vector(
        operation="apply_boolean",
        input_path="shapes.svg",
        output_path="union.svg",
        operation_type="union",
        select_all=True
    )

    # Measure object dimensions
    result = await inkscape_vector(
        operation="measure_object",
        input_path="drawing.svg",
        object_id="circle1"
    )

    # Simplify path with threshold
    result = await inkscape_vector(
        operation="path_simplify",
        input_path="complex.svg",
        output_path="simplified.svg",
        object_id="path1",
        threshold=2.0
    )

    # Render PNG preview at high DPI
    result = await inkscape_vector(
        operation="render_preview",
        input_path="design.svg",
        output_path="preview.png",
        dpi=300
    )

    # Generate animated laser dot
    result = await inkscape_vector(
        operation="generate_laser_dot",
        output_path="laser.svg",
        x=400,
        y=300
    )

    # Query document statistics
    result = await inkscape_vector(
        operation="query_document",
        input_path="document.svg"
    )

Errors:
    - FileNotFoundError: Input file does not exist or is not readable
        Recovery options:
        - Verify file path is correct and accessible
        - Check file permissions (read access required)
        - Ensure file is a valid SVG document

    - ValueError: Invalid parameters or object IDs
        Recovery options:
        - For apply_boolean: Provide object_ids (list with 2+ items) OR set select_all=True
        - Verify operation_type is one of: union, difference, intersection, exclusion
        - Ensure object_id exists in document (use query_document to list IDs)
        - Check all required parameters are provided for the operation

    - InkscapeExecutionError: Inkscape CLI command failed
        Recovery options:
        - Verify Inkscape installation (run inkscape --version)
        - Check CLI arguments are valid for Inkscape version
        - Ensure output directory exists and is writable
        - Check process timeout settings in config
        - Verify object IDs exist in the SVG document

    - NotImplementedError: Operation not yet implemented
        Recovery options:
        - Check supported operations list in documentation
        - Use alternative operations that provide similar functionality
        - Check if operation is available in newer Inkscape versions
"""

import hashlib
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any

from lxml import etree
from pydantic import BaseModel

from ..mcp_tool_types import InkscapeVectorOperation
from .dimensions import size_report

SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"
INK = "{http://www.inkscape.org/namespaces/inkscape}"
SODIPODI = "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}"

# `select-all:all` includes groups AND layers, so a per-object action ends up applied to the
# enclosing layer <g> and silently no-ops. The bare form defaults to 'no-groups' — every
# object other than groups and layers — which is what these operations actually want.
_SELECT_OBJECTS = "select-all"

_SHAPE_TAGS = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "image", "use"})


class Scope(Enum):
    """How an operation relates to `object_id` / `object_ids`.

    OBJECTS  — acts on the given objects; falls back to the whole drawing when none
               are named. Passing ids used to be silently ignored, which turned
               "convert this circle" into "convert every object in the document".
    PAGE     — acts on the page or document as a whole. Ids are meaningless here, so
               they are refused rather than accepted and dropped.
    EXACTLY_N — Inkscape requires a precise number of selected objects (path-division
               and path-cut need two). With the wrong count the underlying action
               silently does nothing, so the count is validated up front.
    """

    OBJECTS = "objects"
    PAGE = "page"
    EXACTLY_N = "exactly_n"


# Operations not listed default to Scope.OBJECTS with no count requirement.
_OP_SCOPE: dict[str, tuple[Scope, int | None]] = {
    # Exactly-N: Inkscape's own requirement, not ours.
    "path_division": (Scope.EXACTLY_N, 2),
    "path_cut": (Scope.EXACTLY_N, 2),
    "path_fill_between": (Scope.EXACTLY_N, 2),
    # Page / document scoped — ids cannot narrow these.
    "page_rotate": (Scope.PAGE, None),
    "set_document_units": (Scope.PAGE, None),
    "fit_canvas_to_drawing": (Scope.PAGE, None),
    "optimize_svg": (Scope.PAGE, None),
    "scour_svg": (Scope.PAGE, None),
    "path_clean": (Scope.PAGE, None),
    "export_dxf": (Scope.PAGE, None),
    "layers_to_files": (Scope.PAGE, None),
    "render_preview": (Scope.PAGE, None),
    "query_document": (Scope.PAGE, None),
    "construct_svg": (Scope.PAGE, None),
    "generate_barcode_qr": (Scope.PAGE, None),
    "generate_laser_dot": (Scope.PAGE, None),
    "trace_image": (Scope.PAGE, None),
}

# Operations Inkscape cannot perform without a GUI desktop. Verified against 1.4.4:
# `path-outset` / `path-inset` / `path-offset` are all inert via the CLI, and the Offset
# LPE never recomputes on a headless export — not even when forced through
# `object-to-path`. Returning a wrong-but-plausible document is worse than refusing.
_REQUIRES_GUI: dict[str, str] = {
    "path_offset": (
        "path_offset needs a running Inkscape GUI: Inkscape's offset actions and the "
        "Offset LPE do not compute headlessly. Open the document and use "
        "inkscape_live(operation='path_offset', target=<path-id>, payload='{\"offset\": N}'). "
        "For a uniform scale of the selection instead, use scale_selection."
    ),
    "lpe_paste": (
        "lpe_paste needs a running Inkscape GUI: it pastes from the live clipboard, which "
        "does not exist headlessly. Pass source_id + object_ids to copy a path effect "
        "between objects, or use inkscape_live for the clipboard-backed behaviour."
    ),
    # Verified headlessly: `text-put-on-path` produces no <textPath> under any selection
    # chain (both ids at once, sequential additive selects, or select-clear first).
    "text_on_path": (
        "text_on_path needs a running Inkscape GUI: Inkscape's text-put-on-path action "
        "produces no <textPath> headlessly under any selection order. Open the document "
        "and drive it via inkscape_live, or author the <textPath> directly with "
        "inkscape_live(operation='edit_xml')."
    ),
    # Verified headlessly: the path-to-mesh extension emits no <meshgradient> off-GUI.
    "create_mesh_gradient": (
        "create_mesh_gradient needs a running Inkscape GUI: the path-to-mesh extension "
        "produces no <meshgradient> headlessly. Open the document and use inkscape_live."
    ),
}

# Renamed operations: old name -> message naming the replacement(s).
_RENAMED: dict[str, str] = {
    "path_inset_outset": (
        "path_inset_outset never offset a path outline — it fired transform-grow, which "
        "uniformly scales the selection so its bounding box grows by the given amount. "
        "Use scale_selection for that behaviour, or path_offset (GUI only) for a true "
        "outline offset."
    ),
}


# Attributes Inkscape rewrites on every export regardless of what the actions did.
_BOOKKEEPING_ATTRS = frozenset(
    {
        f"{INK}version",
        f"{INK}cx",
        f"{INK}cy",
        f"{INK}zoom",
        f"{INK}current-layer",
        f"{INK}window-width",
        f"{INK}window-height",
        f"{INK}window-x",
        f"{INK}window-y",
        f"{INK}window-maximized",
        f"{SODIPODI}docname",
    }
)


def _doc_fingerprint(path: str) -> str | None:
    """Digest of the drawing's content, ignoring Inkscape's reserialisation.

    A byte comparison is useless here: exporting through Inkscape rewrites the file
    even when the actions did nothing — it adds `sodipodi:docname`, an `id` on the
    root, an empty `<defs>`, a `<sodipodi:namedview>` block and namespace declarations,
    and reflows all the whitespace. Every operation would look like it had changed
    something.

    So walk the tree instead and digest what a reader would actually see: each drawable
    element's depth, tag and attributes. Depth matters — it is what distinguishes a
    successful `ungroup` (children promoted a level) from a no-op one, since the set of
    elements is identical either way.

    Returns None when the file can't be parsed; callers treat that as "can't tell" and
    skip the check rather than inventing a failure.
    """
    try:
        root = etree.parse(path).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None

    parts: list[str] = []
    # Page geometry lives on the root and is the whole point of page_rotate /
    # fit_canvas_to_drawing, so it is part of the content even though the root's other
    # attributes are bookkeeping.
    for attr in ("width", "height", "viewBox"):
        parts.append(f"@{attr}={root.get(attr, '')}")

    def walk(elem: Any, depth: int) -> None:
        for child in elem:
            if not isinstance(child.tag, str):
                continue  # comments / processing instructions
            qname = etree.QName(child)
            local = qname.localname
            if local == "namedview" or local == "metadata":
                continue
            if local == "defs" and len(child) == 0:
                continue  # Inkscape adds an empty <defs> to every export
            attrs = sorted(f"{k}={v}" for k, v in child.attrib.items() if k not in _BOOKKEEPING_ATTRS)
            text = (child.text or "").strip()
            parts.append(f"{depth}:{qname.namespace}:{local}:{'|'.join(attrs)}:{text}")
            walk(child, depth + 1)

    walk(root, 1)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _resolve_ids(object_id: str, object_ids: list[str] | None) -> list[str]:
    """Collapse the two id-carrying parameters into one list, preserving order."""
    if object_ids:
        return [i for i in object_ids if i]
    return [object_id] if object_id else []


def _scope_error(operation: str, object_id: str, object_ids: list[str] | None) -> str | None:
    """Validate id arguments against the operation's scope. Returns a message on refusal."""
    scope, required = _OP_SCOPE.get(operation, (Scope.OBJECTS, None))
    ids = _resolve_ids(object_id, object_ids)

    if scope is Scope.PAGE and ids:
        param = "object_ids" if object_ids else "object_id"
        return (
            f"{operation} operates on the page/document as a whole and cannot be scoped to {param}; drop the argument."
        )
    if scope is Scope.EXACTLY_N and ids and len(ids) != required:
        return (
            f"{operation} requires exactly {required} object_ids (Inkscape silently does "
            f"nothing with any other count); got {len(ids)}: {ids}"
        )
    return None


def _select_action(object_id: str = "", object_ids: list[str] | None = None) -> str:
    """Build the selection action, narrowing to ids when any were supplied.

    Mirrors what `_align_or_distribute` and `_apply_boolean` already do — those two were
    the only operations honouring ids, which is why they were also the only ones that
    reliably did what they were asked.
    """
    ids = _resolve_ids(object_id, object_ids)
    return f"select-by-id:{','.join(ids)}" if ids else _SELECT_OBJECTS


class VectorOperationResult(BaseModel):
    """Result model for vector operations."""

    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


def _local_tag(elem: Any) -> str:
    """Strip the XML namespace for cleaner type names."""
    tag = str(elem.tag)
    return tag.split("}", 1)[1] if "}" in tag else tag


def _count_layers(path: str) -> int:
    """Count Inkscape layers (`<g inkscape:groupmode="layer">`), or 0 if unparseable."""
    try:
        root = etree.parse(path).getroot()
    except (OSError, etree.XMLSyntaxError):
        return 0
    return sum(1 for g in root.iter(f"{SVG}g") if g.get(f"{INK}groupmode") == "layer")


def _count_path_elements(path: str) -> int:
    """Count `<path>` elements in an SVG, or -1 if it can't be parsed."""
    try:
        root = etree.parse(path).getroot()
    except (OSError, etree.XMLSyntaxError):
        return -1
    return sum(1 for _ in root.iter(f"{SVG}path"))


async def inkscape_vector(
    operation: InkscapeVectorOperation,
    input_path: str = "",
    output_path: str = "",
    object_id: str = "",
    object_ids: list[str] | None = None,
    select_all: bool = False,
    operation_type: str = "",
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Inkscape vector operations portmanteau tool."""
    start_time = time.time()

    # Refuse before doing any work: a renamed operation, one that cannot run without a
    # GUI, or id arguments the operation can't honour. Each of these used to produce a
    # cheerful success over an unchanged document.
    for table, err in ((_RENAMED, "renamed operation"), (_REQUIRES_GUI, "requires GUI")):
        if operation in table:
            return VectorOperationResult(
                success=False,
                operation=operation,
                message=table[operation],
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error=err,
            ).model_dump()

    scope_problem = _scope_error(operation, object_id, object_ids)
    if scope_problem:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message=scope_problem,
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error="invalid scope",
        ).model_dump()

    try:
        if operation == "trace_image":
            return await _trace_image(
                input_path,
                output_path,
                cli_wrapper,
                config,
                scans=kwargs.get("trace_scans", 4),
                smooth=kwargs.get("trace_smooth", True),
                stack=kwargs.get("trace_stack", True),
                remove_background=kwargs.get("trace_remove_background", False),
                speckles=kwargs.get("trace_speckles", 2),
                smooth_corners=kwargs.get("trace_smooth_corners", 1.0),
                optimize=kwargs.get("trace_optimize", 0.2),
            )

        elif operation == "generate_barcode_qr":
            return await _generate_barcode_qr(kwargs.get("barcode_data", ""), output_path, cli_wrapper, config)

        elif operation == "generate_laser_dot":
            return await _generate_laser_dot(
                output_path, kwargs.get("x", 300), kwargs.get("y", 200), cli_wrapper, config
            )

        elif operation == "measure_object":
            return await _measure_object(input_path, object_id, cli_wrapper, config)

        elif operation == "query_document":
            return await _query_document(input_path, cli_wrapper, config)

        elif operation == "count_nodes":
            return await _count_nodes(input_path, object_id, cli_wrapper, config)

        elif operation == "path_simplify":
            return await _path_simplify(
                input_path,
                output_path,
                object_id,
                kwargs.get("threshold", 1.0),
                cli_wrapper,
                config,
            )

        elif operation == "path_clean":
            return await _path_clean(input_path, output_path, cli_wrapper, config)

        elif operation == "render_preview":
            return await _render_preview(input_path, output_path, kwargs.get("dpi", 96), cli_wrapper, config)

        elif operation == "apply_boolean":
            return await _apply_boolean(
                operation_type, input_path, output_path, object_ids, select_all, cli_wrapper, config
            )

        elif operation == "object_raise":
            return await _object_raise(input_path, output_path, object_id, cli_wrapper, config)

        elif operation == "object_lower":
            return await _object_lower(input_path, output_path, object_id, cli_wrapper, config)

        elif operation == "set_document_units":
            return await _set_document_units(input_path, output_path, kwargs.get("units", "px"), cli_wrapper, config)

        elif operation == "object_to_path":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-to-path"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "text_to_path":
            # Text → path uses the same object-to-path action in 1.4; select text only.
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=["select-by-element:text", "object-to-path"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "fit_canvas_to_drawing":
            # 1.4 renamed the action; old name lives on as our portmanteau alias.
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "fit-canvas-to-selection"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "path_combine":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-combine"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "create_mesh_gradient":
            # Convert the first/all selected path(s) into a mesh gradient via extension action.
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "org.inkscape.meshes.path-to-mesh.noprefs"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "construct_svg":
            return _construct_svg(output_path, kwargs.get("description", ""))

        elif operation == "path_break_apart":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-break-apart"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation in ("optimize_svg", "scour_svg"):
            # Both map to Inkscape's plain-SVG export, which strips the inkscape:/sodipodi:
            # namespaced editor state. `scour_svg` additionally vacuums unreferenced defs.
            return await _optimize_svg(
                operation,
                input_path,
                output_path,
                vacuum_defs=(operation == "scour_svg"),
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "export_dxf":
            return await _export_dxf(input_path, output_path, config)

        elif operation == "layers_to_files":
            return await _layers_to_files(input_path, kwargs.get("output_dir", "") or output_path, cli_wrapper, config)

        elif operation == "scale_selection":
            # `transform-grow:<n>` scales the selection so its bounding box grows by n
            # in total (n/2 per side), preserving shape and aspect ratio. This is NOT a
            # path inset/outset — the old `path_inset_outset` name claimed it was, and
            # now fails with a pointer here (see _RENAMED).
            offset = float(kwargs.get("offset", 1.0))
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), f"transform-grow:{offset:g}"],
                cli_wrapper=cli_wrapper,
                config=config,
                noop_hint="transform-grow needs a non-empty selection; check object_ids",
            )

        elif operation == "path_division":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-division"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "path_cut":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-cut"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "path_split":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-split"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "path_fill_between":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "path-fill-between-paths"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "stroke_to_path":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-stroke-to-path"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "flip_horizontal":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-flip-horizontal"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "flip_vertical":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-flip-vertical"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "rotate_90_cw":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-rotate-90-cw"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "rotate_90_ccw":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-rotate-90-ccw"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "align":
            return await _align_or_distribute(
                operation,
                operation_type,
                input_path,
                output_path,
                object_ids,
                cli_wrapper,
                config,
            )

        elif operation == "distribute":
            return await _align_or_distribute(
                operation,
                operation_type,
                input_path,
                output_path,
                object_ids,
                cli_wrapper,
                config,
            )

        elif operation == "ungroup":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "selection-ungroup"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "clone":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "clone"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "clone_unlink":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "clone-unlink"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "object_to_marker":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-to-marker"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "object_to_pattern":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-to-pattern"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "tile_clone":
            from .tile_clone import tile_clone as _tile_clone

            return _tile_clone(
                input_path=input_path,
                output_path=output_path,
                source_id=kwargs.get("source_id", ""),
                rows=int(kwargs.get("rows", 3)),
                cols=int(kwargs.get("cols", 3)),
                x_shift=float(kwargs.get("x_shift", 50)),
                y_shift=float(kwargs.get("y_shift", 50)),
                rotation_step=float(kwargs.get("rotation_step", 0.0)),
                scale_step=float(kwargs.get("scale_step", 1.0)),
            )

        elif operation == "text_on_path":
            text_id = kwargs.get("text_id", "")
            path_id = kwargs.get("path_id", "")
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[
                    f"select-by-id:{text_id}",
                    f"select-by-id:{path_id}",
                    "text-put-on-path",
                ],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "page_fit_to_selection":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "page-fit-to-selection"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "page_rotate":
            # page-rotate takes an integer arg = number of 90-deg CW steps.
            steps = int(kwargs.get("steps", 1))
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[f"page-rotate:{steps}"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "lpe_add_corners":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "object-add-corners-lpe"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "lpe_remove":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "remove-path-effect"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "lpe_paste":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "paste-path-effect"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        elif operation == "lpe_clone_link":
            return await _simple_action_op(
                operation,
                input_path,
                output_path,
                actions=[_select_action(object_id, object_ids), "clone-link-lpe"],
                cli_wrapper=cli_wrapper,
                config=config,
            )

        else:
            # Placeholder for unimplemented operations
            return VectorOperationResult(
                success=False,
                operation=operation,
                message=f"Operation '{operation}' not yet implemented",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="NotImplementedError",
            ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message=f"Operation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        ).model_dump()


async def _trace_image(
    input_path: str,
    output_path: str,
    cli_wrapper: Any,
    config: Any,
    scans: int = 4,
    smooth: bool = True,
    stack: bool = True,
    remove_background: bool = False,
    speckles: int = 2,
    smooth_corners: float = 1.0,
    optimize: float = 0.2,
) -> dict[str, Any]:
    """Trace bitmap image to vector paths using potrace."""
    start = time.time()
    try:
        # `selection-create-bitmap-copies` / `selection-trace` / `file-save-as` do not exist
        # in 1.4; the trace verb is `object-trace`. The input file is already passed as the
        # positional argument, so `file-open:` is redundant.
        #
        # object-trace REQUIRES its full argument tuple. Fired bare it printed
        # "expected argument format" to stderr, exited 0, and exported the untraced
        # bitmap re-wrapped in an <image> — zero paths, reported as success. Note
        # smooth_corners/optimize are parsed with stod, so they must render as floats
        # ("1" fails with "parsing arguments failed: stod").
        trace_args = ",".join(
            [
                str(int(scans)),
                "true" if smooth else "false",
                "true" if stack else "false",
                "true" if remove_background else "false",
                str(int(speckles)),
                str(float(smooth_corners)),
                str(float(optimize)),
            ]
        )
        actions = [
            _SELECT_OBJECTS,
            f"object-trace:{trace_args}",
            f"export-filename:{output_path}",
            "export-type:svg",
            "export-do",
        ]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        # The trace can still come back empty (blank source, everything below the speckle
        # floor). Report that rather than handing back an <image>-only "vector" file.
        paths_written = _count_path_elements(output_path)
        if paths_written == 0:
            return VectorOperationResult(
                success=False,
                operation="trace_image",
                message=(
                    f"Trace produced no paths for {input_path}; the export contains only the "
                    f"source bitmap. Try more scans or fewer speckles."
                ),
                data={"input_path": input_path, "output_path": output_path, "trace_args": trace_args},
                execution_time_ms=(time.time() - start) * 1000,
                error="no paths traced",
            ).model_dump()

        return VectorOperationResult(
            success=True,
            operation="trace_image",
            message=f"Traced bitmap {input_path} to vector {output_path} ({paths_written} path(s))",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "method": "potrace",
                "paths": paths_written,
                "trace_args": trace_args,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="trace_image",
            message=f"Bitmap tracing failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


_QR_EXTENSION_ID = "org.inkscape.qr_code"

_EMPTY_CANVAS_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
    'viewBox="0 0 200 200" width="200" height="200"/>'
)


async def _generate_barcode_qr(barcode_data: str, output_path: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Render a real QR code via Inkscape's bundled ``org.inkscape.qr_code`` extension.

    The previous implementation wrote the payload into a ``<text>`` element — a label, not a
    scannable code — and reported success. It also interpolated the payload into an XML
    template without escaping, so any ``&`` or ``<`` produced an unparseable file.
    """
    start = time.time()
    try:
        if not barcode_data:
            return VectorOperationResult(
                success=False,
                operation="generate_barcode_qr",
                message="barcode_data is required to generate a QR code",
                data={},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()
        if not output_path:
            return VectorOperationResult(
                success=False,
                operation="generate_barcode_qr",
                message="output_path is required",
                data={},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()

        from .extension import _op_run

        # The QR extension is a generator: it needs a canvas to draw onto, not our input.
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(_EMPTY_CANVAS_SVG, encoding="utf-8")

        res = await _op_run(
            "generate_barcode_qr",
            _QR_EXTENSION_ID,
            {"text": barcode_data},
            str(out_p),
            str(out_p),
            start,
        )
        if not res["success"]:
            out_p.unlink(missing_ok=True)
            return VectorOperationResult(
                success=False,
                operation="generate_barcode_qr",
                message=f"QR generation failed: {res['message']}",
                data=res.get("data", {}),
                execution_time_ms=(time.time() - start) * 1000,
                error=res.get("error", "extension failed"),
            ).model_dump()

        return VectorOperationResult(
            success=True,
            operation="generate_barcode_qr",
            message=f"Generated QR code for: {barcode_data}",
            data={
                "output_path": str(out_p),
                "data": barcode_data,
                "type": "qr",
                "extension": _QR_EXTENSION_ID,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="generate_barcode_qr",
            message=f"Barcode generation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _generate_laser_dot(output_path: str, x: float, y: float, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Generate animated laser pointer dot."""
    start = time.time()
    try:
        svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="800" height="600" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="laserGradient" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:#00FF00;stop-opacity:1" />
      <stop offset="70%" style="stop-color:#00FF00;stop-opacity:0.8" />
      <stop offset="100%" style="stop-color:#00FF00;stop-opacity:0" />
    </radialGradient>
  </defs>

  <!-- Core laser dot with frantic pulsing animation -->
  <circle cx="{x}" cy="{y}" r="15" fill="url(#laserGradient)">
    <animate attributeName="r" values="8;25;8" dur="0.15s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="1;0.3;1" dur="0.12s" repeatCount="indefinite"/>
  </circle>

  <!-- Outer ring with rapid expansion/contraction -->
  <circle cx="{x}" cy="{y}" r="12" fill="none" stroke="#00FF00" stroke-width="3" opacity="0.8">
    <animate attributeName="r" values="12;35;12" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="stroke-width" values="3;1;3" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.8;0.2;0.8" dur="0.2s" repeatCount="indefinite"/>
  </circle>

  <!-- Secondary pulse ring -->
  <circle cx="{x}" cy="{y}" r="6" fill="none" stroke="#00FF00" stroke-width="2" opacity="0.4">
    <animate attributeName="r" values="6;20;6" dur="0.4s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="opacity" values="0.4;0;0.4" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
  </circle>
</svg>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        return VectorOperationResult(
            success=True,
            operation="generate_laser_dot",
            message="Generated animated laser dot SVG",
            data={
                "output_path": output_path,
                "position": {"x": x, "y": y},
                "description": "Animated green laser pointer dot",
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="generate_laser_dot",
            message=f"Laser dot generation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _measure_object(input_path: str, object_id: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Measure object dimensions."""
    start = time.time()
    if not object_id:
        return VectorOperationResult(
            success=False,
            operation="measure_object",
            message="object_id is required; use query_document for whole-drawing dimensions",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="missing object_id",
        ).model_dump()
    try:
        # `--query-x=<id>` is NOT the CLI syntax — the id belongs in `--query-id`, and the
        # four coordinate flags are bare switches. Passing the id to `--query-x` made
        # Inkscape ignore it and answer for the whole drawing, so every object in a
        # document measured identically. All four flags also answer in one invocation,
        # which drops this from four Inkscape launches to one.
        stdout, stderr = await cli_wrapper._execute_command_capture(
            [
                str(config.inkscape_executable),
                "--app-id-tag=mcp",
                input_path,
                "--query-id",
                object_id,
                "--query-x",
                "--query-y",
                "--query-width",
                "--query-height",
            ],
            config.process_timeout,
        )

        # A missing id is a stderr warning + a silent fall back to the drawing bbox.
        if "Did not find object with id" in stderr:
            return VectorOperationResult(
                success=False,
                operation="measure_object",
                message=f"No object with id {object_id!r} in {input_path}",
                data={"object_id": object_id},
                execution_time_ms=(time.time() - start) * 1000,
                error="object not found",
            ).model_dump()

        values = [line for line in stdout.splitlines() if line.strip()]
        if len(values) < 4:
            raise ValueError(f"expected 4 query values, got {values!r}")
        x, y, width, height = (float(v.strip()) for v in values[:4])

        return VectorOperationResult(
            success=True,
            operation="measure_object",
            message=f"Measured object {object_id}",
            data={
                "object_id": object_id,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "bbox": [x, y, x + width, y + height],
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="measure_object",
            message=f"Object measurement failed: {e}",
            data={"object_id": object_id},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _query_document(input_path: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Query document information."""
    start = time.time()
    try:
        # Page and drawing-bbox sizes are different numbers; this used to report only
        # the latter as bare "width"/"height". See tools/dimensions.py.
        report = await size_report(input_path, cli_wrapper, config)

        # Real counts from the XML rather than the previous hardcoded 1/1.
        root = etree.parse(input_path).getroot()
        elems = list(root.iter())
        num_objects = sum(1 for e in elems if _local_tag(e) in _SHAPE_TAGS)
        num_layers = sum(1 for e in elems if _local_tag(e) == "g" and e.get(f"{INK}groupmode") == "layer")
        num_groups = sum(1 for e in elems if _local_tag(e) == "g") - num_layers

        return VectorOperationResult(
            success=True,
            operation="query_document",
            message=f"Queried document {input_path}: {num_objects} object(s), {num_layers} layer(s)",
            data={
                **report,
                "num_objects": num_objects,
                "num_layers": num_layers,
                "num_groups": num_groups,
                "element_count": len(elems),
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="query_document",
            message=f"Document query failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


# One SVG path node per drawing command. Excludes Z/z, which closes back onto the
# subpath's existing start node rather than adding a new one.
_PATH_CMD_RE = re.compile(r"[MmLlHhVvCcSsQqTtAa]")


def _count_path_nodes(d: str) -> int:
    """Count nodes in a path `d` string, accounting for implicit repeated commands.

    `M 0 0 L 1 1 2 2` is three nodes, not two: after an explicit command letter, further
    coordinate tuples repeat it implicitly (subsequent `M` pairs repeat as `L`).
    """
    if not d:
        return 0
    nodes = 0
    for cmd, args in re.findall(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)", d):
        if cmd in "Zz":
            continue
        per_node = {"H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}.get(cmd.upper(), 2)
        count = len(re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", args))
        nodes += max(1, count // per_node)
    return nodes


async def _count_nodes(input_path: str, object_id: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Count bezier nodes across the document, or in one path when object_id is given."""
    start = time.time()
    try:
        root = etree.parse(input_path).getroot()
        per_path: dict[str, int] = {}
        for el in root.iter(f"{SVG}path"):
            el_id = el.get("id", "")
            if object_id and el_id != object_id:
                continue
            per_path[el_id] = _count_path_nodes(el.get("d", ""))

        if object_id and not per_path:
            return VectorOperationResult(
                success=False,
                operation="count_nodes",
                message=f"no <path> with id {object_id!r} in {input_path}",
                data={"object_id": object_id},
                execution_time_ms=(time.time() - start) * 1000,
                error="NotFound",
            ).model_dump()

        total = sum(per_path.values())
        scope = f"object {object_id}" if object_id else f"{len(per_path)} path(s)"
        return VectorOperationResult(
            success=True,
            operation="count_nodes",
            message=f"Counted {total} node(s) across {scope}",
            data={
                "object_id": object_id,
                "node_count": total,
                "paths": per_path,
                "path_count": len(per_path),
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="count_nodes",
            message=f"Node counting failed: {e}",
            data={"object_id": object_id},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _path_simplify(
    input_path: str,
    output_path: str,
    object_id: str,
    threshold: float,
    cli_wrapper: Any,
    config: Any,
) -> dict[str, Any]:
    """Simplify path by reducing nodes."""
    start = time.time()
    try:
        # `path-simplify` takes no argument in 1.4 — the aggressiveness comes from Inkscape's
        # simplification-threshold preference. We approximate `threshold` by applying the
        # action repeatedly, which is how Inkscape's own repeated-Ctrl+L behaves.
        passes = max(1, min(10, round(threshold)))
        select = f"select-by-id:{object_id}" if object_id else _SELECT_OBJECTS
        actions = [
            select,
            *(["path-simplify"] * passes),
            f"export-filename:{output_path}",
            "export-do",
        ]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="path_simplify",
            message=f"Simplified path for object {object_id}",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "object_id": object_id,
                "threshold": threshold,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="path_simplify",
            message=f"Path simplification failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _path_clean(input_path: str, output_path: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Clean SVG by removing unnecessary elements."""
    start = time.time()
    try:
        # `file-vacuum-defs` / `file-cleanup` do not exist in 1.4. `export-plain-svg` is the
        # supported cleanup path: it drops Inkscape/sodipodi-namespaced cruft on export.
        actions = [
            "export-plain-svg",
            f"export-filename:{output_path}",
            "export-do",
        ]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="path_clean",
            message=f"Cleaned SVG {input_path}",
            data={
                "input_path": input_path,
                "output_path": output_path,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="path_clean",
            message=f"Path cleaning failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _construct_svg(output_path: str, description: str) -> dict[str, Any]:
    """Emit a minimal SVG scaffold so agents can build up from a known starting point."""
    start = time.time()
    if not output_path:
        return VectorOperationResult(
            success=False,
            operation="construct_svg",
            message="Output path required",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="ValueError",
        ).model_dump()
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200" version="1.1">\n'
        f"  <title>{description or 'constructed-svg'}</title>\n"
        '  <g id="root-layer" inkscape:groupmode="layer" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" />\n'
        "</svg>\n"
    )
    Path(output_path).write_text(body, encoding="utf-8")
    return VectorOperationResult(
        success=True,
        operation="construct_svg",
        message=f"Wrote scaffold SVG to {output_path}",
        data={"output_path": output_path, "description": description},
        execution_time_ms=(time.time() - start) * 1000,
    ).model_dump()


async def _simple_action_op(
    operation: str,
    input_path: str,
    output_path: str,
    actions: list[str],
    cli_wrapper: Any,
    config: Any,
    expect_change: bool = True,
    noop_hint: str = "",
) -> dict[str, Any]:
    """Apply a chained list of Inkscape actions, write to output_path.

    Inkscape exits 0 whether or not an action did anything — a wrong selection, an
    unmet object-count requirement or a GUI-only action all leave the drawing untouched
    and still produce an output file. So the drawing is fingerprinted before and after
    and an unchanged result is reported as a failure.

    Set `expect_change=False` for operations where "nothing to do" is a legitimate
    outcome (e.g. cleaning an already-clean file).
    """
    start = time.time()
    if not output_path:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message="Output path required",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="ValueError",
        ).model_dump()
    try:
        before = _doc_fingerprint(input_path) if expect_change else None
        full_actions = [*list(actions), f"export-filename:{output_path}", "export-type:svg", "export-do"]
        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=full_actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        if expect_change and before is not None:
            after = _doc_fingerprint(output_path)
            if after is not None and after == before:
                hint = noop_hint or (
                    "the selection may not match what this action needs — check object_ids, "
                    "the required object count, and whether the operation needs a GUI"
                )
                return VectorOperationResult(
                    success=False,
                    operation=operation,
                    message=f"{operation} changed nothing (no-op): {hint}",
                    data={
                        "input_path": input_path,
                        "output_path": output_path,
                        "actions": actions,
                    },
                    execution_time_ms=(time.time() - start) * 1000,
                    error="no-op",
                ).model_dump()

        return VectorOperationResult(
            success=True,
            operation=operation,
            message=f"Applied {operation} to {input_path}",
            data={"input_path": input_path, "output_path": output_path, "actions": actions},
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message=f"{operation} failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _render_preview(input_path: str, output_path: str, dpi: int, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Render PNG preview of SVG."""
    start = time.time()
    try:
        actions = [f"export-filename:{output_path}", f"export-dpi:{dpi}", "export-do"]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="render_preview",
            message=f"Rendered preview of {input_path}",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "dpi": dpi,
                "format": "png",
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="render_preview",
            message=f"Preview rendering failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


_ALIGN_POSITIONS = frozenset({"left", "hcenter", "right", "top", "vcenter", "bottom"})
_ALIGN_ANCHORS = frozenset({"last", "first", "biggest", "smallest", "page", "drawing", "selection", "pref"})
_DISTRIBUTE_MODES = frozenset({"hgap", "left", "hcenter", "right", "vgap", "top", "vcenter", "bottom"})


async def _align_or_distribute(
    operation: str,
    operation_type: str,
    input_path: str,
    output_path: str,
    object_ids: list[str] | None,
    cli_wrapper: Any,
    config: Any,
) -> dict[str, Any]:
    """Align or distribute the selection along `operation_type`.

    Both `object-align` and `object-distribute` REQUIRE an argument. Fired bare they
    print "expected argument format" to stderr, exit 0, and leave the drawing
    untouched — which is exactly what these two operations used to do.
    """
    start = time.time()

    if operation == "align":
        tokens = operation_type.split()
        positions = [t for t in tokens if t in _ALIGN_POSITIONS]
        unknown = [t for t in tokens if t not in _ALIGN_POSITIONS | _ALIGN_ANCHORS]
        valid = bool(positions) and not unknown
        expected = (
            "one or two positions (left|hcenter|right and/or top|vcenter|bottom), "
            "optionally followed by an anchor (last|first|biggest|smallest|page|drawing|selection|pref) "
            "— e.g. 'top', 'left', 'hcenter vcenter', 'top page'"
        )
        action = "object-align"
    else:
        tokens = operation_type.split()
        valid = len(tokens) == 1 and tokens[0] in _DISTRIBUTE_MODES
        expected = "exactly one of hgap|left|hcenter|right|vgap|top|vcenter|bottom — e.g. 'hgap'"
        action = "object-distribute"

    if not valid:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message=(
                f"{operation} requires operation_type to be {expected}; got {operation_type!r}"
                if operation_type
                else f"{operation} requires operation_type: {expected}"
            ),
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="invalid operation_type",
        ).model_dump()

    select_action = f"select-by-id:{','.join(object_ids)}" if object_ids else _SELECT_OBJECTS
    result = await _simple_action_op(
        operation,
        input_path,
        output_path,
        actions=[select_action, f"{action}:{operation_type}"],
        cli_wrapper=cli_wrapper,
        config=config,
    )
    if result.get("success"):
        result["message"] = f"Applied {operation} '{operation_type}' to {input_path}"
        result["data"]["operation_type"] = operation_type
        result["data"]["object_ids"] = object_ids or "all"
    return result


async def _apply_boolean(
    boolean_type: str,
    input_path: str,
    output_path: str,
    object_ids: list[str] | None = None,
    select_all: bool = False,
    cli_wrapper: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """Apply boolean operations with a select → modify → export action chain."""
    start = time.time()
    try:
        # CRITICAL: Build proper action chain - Select → Modify → Persist
        if select_all:
            select_action = _SELECT_OBJECTS
        elif object_ids:
            select_action = f"select-by-id:{','.join(object_ids)}"
        else:
            return VectorOperationResult(
                success=False,
                operation="apply_boolean",
                message="Must provide either object_ids or select_all=true for boolean operations",
                data={},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()

        # Inkscape 1.4 names these path-*, not selection-* (the latter don't exist and are
        # silently skipped, leaving an unmodified export that still reports success).
        operation_map = {
            "union": "path-union",
            "difference": "path-difference",
            "intersection": "path-intersection",
            "exclusion": "path-exclusion",
        }

        if boolean_type not in operation_map:
            return VectorOperationResult(
                success=False,
                operation="apply_boolean",
                message=f"Unknown boolean operation: {boolean_type}",
                data={},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()

        operation_action = operation_map[boolean_type]

        # Complete action chain with export for persistence.
        actions = [select_action, operation_action, f"export-filename:{output_path}", "export-do"]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="apply_boolean",
            message=f"Applied {boolean_type} boolean operation with proper stateful execution",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "operation": boolean_type,
                "selection_method": "select_all" if select_all else "object_ids",
                "object_ids": object_ids or ["all"],
                "action_chain": actions,  # For debugging/transparency
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="apply_boolean",
            message=f"Boolean operation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _object_raise(
    input_path: str, output_path: str, object_id: str, cli_wrapper: Any, config: Any
) -> dict[str, Any]:
    """Raise object in Z-order (move up)."""
    start = time.time()
    try:
        actions = [
            f"select-by-id:{object_id}",
            "selection-raise",
            f"export-filename:{output_path}",
            "export-do",
        ]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="object_raise",
            message=f"Raised object {object_id} in Z-order",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "object_id": object_id,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="object_raise",
            message=f"Object raise failed: {e}",
            data={"object_id": object_id},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _object_lower(
    input_path: str, output_path: str, object_id: str, cli_wrapper: Any, config: Any
) -> dict[str, Any]:
    """Lower object in Z-order (move down)."""
    start = time.time()
    try:
        actions = [
            f"select-by-id:{object_id}",
            "selection-lower",
            f"export-filename:{output_path}",
            "export-do",
        ]

        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=output_path,
            timeout=config.process_timeout,
        )

        return VectorOperationResult(
            success=True,
            operation="object_lower",
            message=f"Lowered object {object_id} in Z-order",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "object_id": object_id,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="object_lower",
            message=f"Object lower failed: {e}",
            data={"object_id": object_id},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _set_document_units(
    input_path: str, output_path: str, units: str, cli_wrapper: Any, config: Any
) -> dict[str, Any]:
    """Set the document's display units by rewriting width/height, preserving the viewBox.

    Previously a no-op that reported success. Rewriting width/height with a unit suffix
    while leaving viewBox alone is the SVG-correct way to change display units without
    moving any geometry: user-space coordinates stay put, only the physical size changes.
    """
    start = time.time()
    _VALID_UNITS = {"px", "mm", "cm", "in", "pt", "pc"}
    try:
        if units not in _VALID_UNITS:
            return VectorOperationResult(
                success=False,
                operation="set_document_units",
                message=f"unsupported unit {units!r}; valid: {sorted(_VALID_UNITS)}",
                data={"requested_units": units},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()
        if not output_path:
            return VectorOperationResult(
                success=False,
                operation="set_document_units",
                message="output_path is required",
                data={},
                execution_time_ms=(time.time() - start) * 1000,
                error="ValueError",
            ).model_dump()

        tree = etree.parse(input_path)
        root = tree.getroot()

        viewbox = root.get("viewBox")
        if not viewbox:
            # Without a viewBox, width/height *are* the user-space extent; synthesise one
            # first so changing the unit suffix doesn't rescale the drawing.
            w_num = _strip_unit(root.get("width", "")) or 0.0
            h_num = _strip_unit(root.get("height", "")) or 0.0
            if not (w_num and h_num):
                return VectorOperationResult(
                    success=False,
                    operation="set_document_units",
                    message="document has neither a viewBox nor numeric width/height",
                    data={"requested_units": units},
                    execution_time_ms=(time.time() - start) * 1000,
                    error="InvalidState",
                ).model_dump()
            root.set("viewBox", f"0 0 {w_num:g} {h_num:g}")
            viewbox = root.get("viewBox")

        vb_parts = [float(v) for v in re.split(r"[ ,]+", str(viewbox).strip()) if v]
        vb_w, vb_h = (vb_parts[2], vb_parts[3]) if len(vb_parts) >= 4 else (0.0, 0.0)

        previous = {"width": root.get("width"), "height": root.get("height")}
        root.set("width", f"{vb_w:g}{units}")
        root.set("height", f"{vb_h:g}{units}")
        root.set(f"{INK}document-units", units)

        from ._svg_io import write_tree

        write_tree(tree, output_path)

        return VectorOperationResult(
            success=True,
            operation="set_document_units",
            message=f"Set document units to {units} ({vb_w:g}x{vb_h:g}{units})",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "requested_units": units,
                "width": f"{vb_w:g}{units}",
                "height": f"{vb_h:g}{units}",
                "viewBox": viewbox,
                "previous": previous,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()

    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="set_document_units",
            message=f"Document units setting failed: {e}",
            data={"requested_units": units},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _strip_unit(raw: str) -> float | None:
    """Parse the numeric part of an SVG length like '210mm' → 210.0."""
    m = re.match(r"\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)", raw or "")
    return float(m.group(1)) if m else None


def _run_scour(path: str) -> None:
    """Minify `path` in place with scour.

    `scour_svg` used to be a pure alias of `optimize_svg` — identical action chain,
    byte-identical output — while scour itself was never imported. Inkscape's
    plain-SVG export pretty-prints one attribute per line, so "optimizing" a small
    file reliably made it *bigger*; this is the pass that actually shrinks it.
    """
    from scour import scour

    options = scour.generateDefaultOptions()
    options.remove_metadata = True
    options.strip_comments = True
    options.strip_xml_prolog = False
    options.enable_viewboxing = False  # keep width/height — callers rely on them
    options.shorten_ids = False  # ids are the addressing scheme for every other op
    options.indent_type = "none"
    options.newlines = False
    options.digits = 5

    original = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(scour.scourString(original, options), encoding="utf-8")


async def _optimize_svg(
    operation: str,
    input_path: str,
    output_path: str,
    *,
    vacuum_defs: bool,
    cli_wrapper: Any,
    config: Any,
) -> dict[str, Any]:
    """Strip editor state via Inkscape's plain-SVG export; optionally drop unused defs.

    Inkscape 1.4 has no `file-vacuum-defs` action, so the unreferenced-defs sweep is done
    here in lxml after the export.

    `scour_svg` additionally runs the file through scour to actually minify it;
    `optimize_svg` stops after the plain-SVG export and the defs sweep.
    """
    start = time.time()
    if not output_path:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message="output_path is required",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="ValueError",
        ).model_dump()
    try:
        size_before = Path(input_path).stat().st_size
        # Plain-SVG export drops the whole inkscape: namespace, which silently demotes every
        # layer to a bare <g>. That is the point of "plain SVG", but callers should be told.
        layers_before = _count_layers(input_path)
        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=["export-plain-svg", f"export-filename:{output_path}", "export-type:svg", "export-do"],
            output_path=output_path,
            timeout=config.process_timeout,
        )

        removed = 0
        if vacuum_defs:
            removed = _vacuum_unused_defs(output_path)

        scoured = operation == "scour_svg"
        if scoured:
            _run_scour(output_path)

        size_after = Path(output_path).stat().st_size
        return VectorOperationResult(
            success=True,
            operation=operation,
            message=(
                f"Optimized {input_path} → {output_path} "
                f"({size_before} → {size_after} bytes, {removed} unused def(s) removed"
                f"{', scoured' if scoured else ''})"
                + (
                    f". Plain-SVG export demoted {layers_before} Inkscape layer(s) to plain groups."
                    if layers_before
                    else ""
                )
            ),
            data={
                "input_path": input_path,
                "output_path": output_path,
                "bytes_before": size_before,
                "bytes_after": size_after,
                "unused_defs_removed": removed,
                "scoured": scoured,
                "layers_demoted": layers_before,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation=operation,
            message=f"{operation} failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


def _vacuum_unused_defs(path: str) -> int:
    """Delete <defs> children whose id is never referenced as url(#id), #id or href="#id"."""
    tree = etree.parse(path)
    root = tree.getroot()
    body = etree.tostring(root, encoding="unicode")
    removed = 0
    for defs in list(root.iter(f"{SVG}defs")):
        for child in list(defs):
            cid = child.get("id")
            if not cid:
                continue
            # Count references outside the element's own serialisation.
            own = etree.tostring(child, encoding="unicode")
            rest = body.replace(own, "", 1)
            if f"url(#{cid})" in rest or f'href="#{cid}"' in rest or f"href='#{cid}'" in rest:
                continue
            defs.remove(child)
            removed += 1
    if removed:
        from ._svg_io import write_tree

        write_tree(tree, path)
    return removed


# Inkscape's DXF R14 outline exporter. Ships with Inkscape; invoked as an output extension
# because `--export-type` only accepts [svg,png,ps,eps,pdf,emf,wmf,xaml] in 1.4.
_DXF_EXTENSION_ID = "org.ekips.output.dxf_outlines"


async def _export_dxf(input_path: str, output_path: str, config: Any) -> dict[str, Any]:
    """Export to DXF via Inkscape's bundled dxf_outlines output extension."""
    start = time.time()
    if not output_path:
        return VectorOperationResult(
            success=False,
            operation="export_dxf",
            message="output_path is required",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="ValueError",
        ).model_dump()
    try:
        from .extension import _op_run

        res = await _op_run("export_dxf", _DXF_EXTENSION_ID, {}, str(Path(input_path).resolve()), output_path, start)
        if not res["success"]:
            return VectorOperationResult(
                success=False,
                operation="export_dxf",
                message=f"DXF export failed: {res['message']}",
                data=res.get("data", {}),
                execution_time_ms=(time.time() - start) * 1000,
                error=res.get("error", "extension failed"),
            ).model_dump()
        return VectorOperationResult(
            success=True,
            operation="export_dxf",
            message=f"Exported {input_path} to DXF at {output_path}",
            data={
                "input_path": input_path,
                "output_path": output_path,
                "bytes": Path(output_path).stat().st_size,
                "extension": _DXF_EXTENSION_ID,
            },
            execution_time_ms=(time.time() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="export_dxf",
            message=f"DXF export failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()


async def _layers_to_files(input_path: str, output_dir: str, cli_wrapper: Any, config: Any) -> dict[str, Any]:
    """Export each inkscape:groupmode="layer" group to its own PNG."""
    start = time.time()
    if not output_dir:
        return VectorOperationResult(
            success=False,
            operation="layers_to_files",
            message="output_dir (or output_path) is required",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error="ValueError",
        ).model_dump()
    try:
        root = etree.parse(input_path).getroot()
        layers = [el for el in root.iter(f"{SVG}g") if el.get(f"{INK}groupmode") == "layer" and el.get("id")]
        if not layers:
            return VectorOperationResult(
                success=False,
                operation="layers_to_files",
                message=f"no inkscape layers found in {input_path}",
                data={"input_path": input_path},
                execution_time_ms=(time.time() - start) * 1000,
                error="NotFound",
            ).model_dump()

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[dict[str, Any]] = []
        for layer in layers:
            layer_id = str(layer.get("id"))
            label = layer.get(f"{INK}label") or layer_id
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_") or layer_id
            dest = out_dir / f"{safe}.png"
            try:
                await cli_wrapper._execute_actions(
                    input_path=input_path,
                    actions=[
                        f"export-id:{layer_id}",
                        "export-id-only:true",
                        f"export-filename:{dest}",
                        "export-type:png",
                        "export-do",
                    ],
                    output_path=str(dest),
                    timeout=config.process_timeout,
                )
                written.append({"layer_id": layer_id, "label": label, "path": str(dest), "success": True})
            except Exception as exc:
                written.append(
                    {
                        "layer_id": layer_id,
                        "label": label,
                        "path": str(dest),
                        "success": False,
                        "error": str(exc),
                    }
                )

        ok = sum(1 for w in written if w["success"])
        return VectorOperationResult(
            success=ok == len(layers),
            operation="layers_to_files",
            message=f"Exported {ok}/{len(layers)} layer(s) to {out_dir}",
            data={"input_path": input_path, "output_dir": str(out_dir), "layers": written},
            execution_time_ms=(time.time() - start) * 1000,
            error="" if ok == len(layers) else "partial export",
        ).model_dump()
    except Exception as e:
        return VectorOperationResult(
            success=False,
            operation="layers_to_files",
            message=f"layers_to_files failed: {e}",
            data={},
            execution_time_ms=(time.time() - start) * 1000,
            error=str(e),
        ).model_dump()
