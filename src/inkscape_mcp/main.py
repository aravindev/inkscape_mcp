"""
Inkscape MCP Server — FastMCP 3.1+ portmanteau entry point.

Exposes MCP tools that shell out to the Inkscape CLI plus registered
MCP prompts/resources (see prompts_resources.py).
"""

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import load_config
from .inkscape_detector import InkscapeDetector
from .logging_config import setup_logging
from .mcp_tool_types import (
    InkscapeAnalysisOperation,
    InkscapeExtensionOperation,
    InkscapeFileOperation,
    InkscapeGradientOperation,
    InkscapeLiveOperation,
    InkscapeMetadataOperation,
    InkscapeSystemOperation,
    InkscapeVectorOperation,
)
from .prompts_resources import register_prompts_and_resources
from .tools import inkscape_analysis as inkscape_analysis_tool
from .tools import inkscape_extension as inkscape_extension_tool
from .tools import inkscape_file as inkscape_file_tool
from .tools import inkscape_gradient as inkscape_gradient_tool
from .tools import inkscape_live as inkscape_live_tool
from .tools import inkscape_metadata as inkscape_metadata_tool
from .tools import inkscape_system as inkscape_system_tool
from .tools import inkscape_vector as inkscape_vector_tool
from .transport import run_server_async

# Import Prefab UI
register_prefabs: Callable[[FastMCP], bool] | None
try:
    from .prefab import register_prefabs

    PREFAB_AVAILABLE = True
except ImportError:
    register_prefabs = None
    PREFAB_AVAILABLE = False

# Configure structured logging
logger = setup_logging(component="main")


# Default operating guidance surfaced to every MCP client on connect. Steers agents
# toward live, in-place editing of the user's open document and toward Inkscape's own
# tools instead of hand-authoring SVG.
SERVER_INSTRUCTIONS = """\
Inkscape MCP drives Inkscape both headlessly (CLI) and on a LIVE, already-open Inkscape
window (the `inkscape_live` tool, over D-Bus).

READ FIRST for anything beyond a one-liner: `resource://inkscape/mcp-workflow` is the
operational guide — which op covers which task, action gotchas, recipes, and Inkscape
rendering pitfalls that will silently ruin output if you don't know them (feDropShadow
is silently broken in 1.4; filters need `inkscape:auto-region="false"` or their bounds
get clamped). `resource://inkscape/cli-actions` is the full verb catalog for when
`list_actions` filtering isn't enough. Reading these costs one call and saves rework.

## You are a designer at a workstation, not an SVG text generator

Do NOT compute an entire drawing as hand-written SVG and paste it in. That is the
failure mode this server exists to prevent — it produces brittle coordinates, no
reuse, and a document the user can't edit afterwards. Instead BUILD IT UP the way a
designer would, one Inkscape operation at a time:

- **Place primitives, then relate them.** Drop rough shapes, then let Inkscape do the
  geometry: `inkscape_vector` `align` / `distribute` for layout, `apply_boolean`
  (union/difference/intersection/exclusion) to cut and merge components,
  `path_inset_outset`, `stroke_to_path`, `path_combine`. Never hand-compute a
  coordinate that an alignment op can derive.
- **Compose, don't duplicate.** Reuse via `clone` / `tile_clone` / `object_to_marker` /
  `object_to_pattern` and `<symbol>`/`<use>`, so one edit updates every instance.
- **Effects belong to Inkscape.** Filters, blurs, shadows, path effects and tracing go
  through `inkscape_extension` `run_live` (no params) or the LPE ops — not hand-authored
  filter primitives, unless the pitfalls doc tells you to.
- **Give every meaningful element a stable `id`** as you create it. Ids are the handle
  for every later edit; unaddressable geometry has to be rebuilt instead of adjusted.
- **Work incrementally and keep it undoable.** Each call is one Inkscape undo entry, so
  the user can step back through your work and co-edit alongside you.

## Look at your work

You have eyes: `inkscape_live` `rasterize` renders the document, one element, or a
region to PNG — read the image back. After anything visual, LOOK at the result rather
than assuming the SVG you wrote renders as intended. Occlusion, clipped filter regions,
invisible elements and colour mistakes are only obvious in the raster. `inspect_element`
gives the post-transform bbox and the fully-cascaded computed style when you need
numbers instead of pixels.

## Work WITH the person at the keyboard

This is a shared canvas, so collaborate rather than guess:

- **Ask them to select.** When the target is ambiguous ("fix the spacing", "recolor
  this"), ask the user to select the object or group on canvas, then read it with
  `get_selection` / `inspect_selection`. That is faster and less error-prone than
  inferring intent from the XML.
- **Show them what you mean.** `set_selection` selects your candidate on their canvas
  so they can see what you're about to change before you change it.
- **Open the UI for them.** They can ask for any dialog or tool and you can open it.
  `apply_action("dialog-open", payload=<name>)` where <name> is one of:
  AlignDistribute, Clonetiler, DocumentProperties, Export, FillStroke, FilterEffects,
  Find, Glyphs, IconPreview, Input, LivePathEffect, Memory, Messages, ObjectAttributes,
  ObjectProperties, Objects, PaintServers, Selectors, Spellcheck, SVGFonts, Swatches,
  Symbols, Text, Trace, Transform, UndoHistory, XMLEditor.
  `apply_action("tool-switch", payload=<name>)` where <name> is one of:
  Arc, Booleans, Calligraphic, Connector, Dropper, Eraser, Gradient, LPETool, Measure,
  Mesh, Node, PaintBucket, Pen, Pencil, Rect, Select, Spiral, Spray, Star, Text, Tweak,
  Zoom.
  Answering "where is that setting?" by opening the dialog on their screen beats
  describing a menu path. Opening dialogs and switching tools is read-only — it never
  edits the document.

## Mechanics

1. Work on the user's OPEN document in place. If Inkscape is running, use `inkscape_live`
   to read and edit that live document instead of creating a new file — `inkscape_live`
   with operation `ping` reports whether the bridge is live. Every live edit is a normal,
   undoable Inkscape command, so a human can co-edit alongside you. NEVER use `open_file`
   to reload or "refresh" a document you are already editing: it opens a NEW window and
   breaks the shared canvas. Apply every change in place (edit_xml / apply_action / the
   effect tools); reserve `open_file` for opening a file the user explicitly asks to open.

2. Prefer Inkscape's own tools over hand-writing SVG when a LIVE one exists: `apply_action`
   (any Inkscape action), `inkscape_extension` `run_live` for filters and effects (drop
   shadow, blur, tracing, path effects), plus `path_edit` and the `inspect_*` reads. Note
   the `inkscape_gradient` and `inkscape_extension` `run` tools are HEADLESS — they operate
   on a file, not the live document, so do not use them for live in-place work. For live
   edits with no native op (e.g. editing a gradient on the open document), use
   `inkscape_live` `edit_xml` (raw-SVG append/set_attr/remove).

   `run_live` has two modes and they are NOT interchangeable. Call it with NO params to
   apply a *transformer* (filter, drop shadow, blur, colour shift, path effect): that
   fires the extension over D-Bus against the real document and the real selection, so
   set the selection first with `set_selection`. Passing params instead renders the
   extension on an EMPTY canvas and appends the result — right for *generator*
   extensions (qr, barcode, calendar, gears), wrong for anything that must transform
   existing content.

3. For live structural edits, `edit_xml` is the reliable, persisting path: it targets
   nodes by XPath and saves in place. `set_attr`/`remove` accept a multi-node XPath
   (e.g. `//*[@id='g']/*[position()>9]`). Note: `execute_inkex` does not currently persist
   document mutations — do not rely on it for edits.

4. Clipboard-based `insert_svg` needs `wl-copy` (wl-clipboard) or `xclip` on PATH; on a
   Wayland session it falls back to `xclip` via XWayland. With neither installed,
   `insert_svg` is unavailable — insert content with `edit_xml` `append` instead.
"""


class InkscapeMCPServer:
    """Main server class for Inkscape MCP integration."""

    def __init__(self, config_path: Path | None = None):
        """Initialize the Inkscape MCP Server.

        Args:
            config_path: Optional path to configuration file
        """
        # load_config(None) already resolves the default ~/.config/inkscape_mcp/config.yaml
        # and layers the INKSCAPE_* env overrides on top. Short-circuiting to a bare
        # InkscapeConfig() when no --config was passed made both permanently dead.
        self.config = load_config(config_path)
        self.mcp = FastMCP("Inkscape MCP Server", instructions=SERVER_INSTRUCTIONS)
        self.tools: dict[str, Any] = {}
        self.logger = logging.getLogger(__name__)
        self.cli_wrapper: Any | None = None

    def _record_config_source(self, name: str, value: Any) -> None:
        """Stamp a setting as auto-detected so `diagnostics` reports its real provenance."""
        from .config import ConfigSource, Resolved

        sources = getattr(self.config, "_sources", None)
        if sources is not None:
            sources[name] = Resolved(value, ConfigSource.AUTO_DETECTED, detail="found on $PATH")

    def _validate_configuration(self) -> bool:
        """Validate server configuration."""
        try:
            required_attrs = ["allowed_directories", "max_file_size_mb"]
            for attr in required_attrs:
                if not hasattr(self.config, attr):
                    logger.error(f"Missing required configuration attribute: {attr}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            return False

    async def initialize(self) -> bool:
        """Initialize server components and register tools."""
        try:
            logger.info("Initializing Inkscape MCP Server...")

            if not self._validate_configuration():
                return False

            # Initialize Inkscape detector. Only fall back to PATH detection when nothing
            # explicitly configured the binary — this used to run unconditionally and
            # overwrite an INKSCAPE_BIN / config-file value with whatever was on PATH,
            # silently defeating the documented way to pin a non-default Inkscape.
            self.inkscape_detector = InkscapeDetector()
            configured = self.config.inkscape_executable
            if configured:
                inkscape_path: str | None = str(configured)
                logger.info(f"Using configured Inkscape: {inkscape_path}")
            else:
                inkscape_path = self.inkscape_detector.detect_inkscape_installation()

            if inkscape_path:
                if not configured:
                    logger.info(f"Found Inkscape at: {inkscape_path}")
                    self._record_config_source("inkscape_executable", inkscape_path)
                self.config.inkscape_executable = str(inkscape_path)

                try:
                    from .cli_wrapper import InkscapeCliWrapper

                    self.cli_wrapper = InkscapeCliWrapper(self.config)
                    logger.info("Initialized Inkscape CLI wrapper")
                except Exception as e:
                    logger.error(f"Failed to initialize Inkscape CLI wrapper: {e}")
                    self.cli_wrapper = None
            else:
                logger.warning("Inkscape not found. Running in limited functionality mode")
                self.cli_wrapper = None

            # Register portmanteau tools
            self._register_portmanteau_tools()

            # loguru does not do %-style interpolation, so these must be f-strings —
            # otherwise the arguments are dropped and the literal %s is logged.
            try:
                register_prompts_and_resources(self.mcp)
                logger.info("MCP prompts and resources registered")
            except Exception as e:
                logger.warning(f"Failed to register prompts/resources: {e}")

            try:
                from .extension_bridge import install_plugins

                install_result = install_plugins()
                if install_result.get("action") == "copied":
                    count = len(install_result.get("files", []))
                    logger.info(f"Extension bridge: installed {count} plugin(s); Inkscape restart required")
                else:
                    logger.info(f"Extension bridge: plugins up to date (v{install_result.get('version')})")
            except Exception as e:
                logger.warning(f"Extension bridge install failed (continuing): {e}")

            # Register Prefab UI (FastMCP 3.2 GenerativeUI)
            if PREFAB_AVAILABLE and register_prefabs is not None:
                try:
                    # Only claim registration when it actually happened — register_prefabs
                    # returns False (rather than raising) when prefab-ui isn't installed.
                    if register_prefabs(self.mcp):
                        logger.info("Prefab UI components registered")
                except Exception as e:
                    logger.warning(f"Failed to register Prefab UI: {e}")

            return True

        except Exception as e:
            logger.error(f"Critical error during initialization: {e}", exc_info=True)
            return False

    def _register_portmanteau_tools(self) -> None:
        """Register all portmanteau tools with FastMCP (ToolBench-aligned Literals + annotations)."""

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_file(
            operation: InkscapeFileOperation,
            input_path: str = "",
            output_path: str = "",
            format: str = "",
            input_paths: list[str] | None = None,
            output_dir: str = "",
            quality: int = 90,
            pdf_version: str = "",
            pdf_page: int = 1,
            margin: float = 0,
            latex: bool = False,
            ignore_filters: bool = False,
            png_color_mode: str = "",
            png_dithering: bool = False,
            validate_structure: bool = True,
        ) -> dict[str, Any]:
            """INKSCAPE_FILE — Load, convert, export, and validate SVG/other files via Inkscape CLI.

            PORTMANTEAU RATIONALE: One tool keeps file I/O discoverable without dozens of
            single-purpose tools; `operation` selects the CLI behavior.

            Operations:
            - load: Read/validate path exists for editing workflows.
            - save: Persist changes (requires paths per server policy).
            - convert: Export to pdf/png/etc. (needs output_path, format).
            - info: Metadata and dimensions.
            - validate: Structural check via CLI query.
            - list_formats: Bounded list of supported export formats (no disk read required).

            Args:
                operation: Must be one of the Literal values (schema-enumerated).
                input_path: Source file; may be empty for list_formats/batch_convert.
                output_path: Destination for save/convert when applicable.
                format: Target format for convert/batch_convert (e.g. pdf, png).
                input_paths: Source files for batch_convert (required for that operation).
                output_dir: Destination directory for batch_convert (required).
                quality: Encoder quality 1-100 for the Pillow-backed formats (jpeg/webp/avif).
                pdf_version, margin, latex, ignore_filters, png_color_mode, png_dithering:
                    Export tuning forwarded to Inkscape's export-* actions.
                pdf_page: Page to read when input_path is a PDF.
                validate_structure: Run Inkscape's query check during load.

            Returns:
                Dict with success, operation, message, data, execution_time_ms, and error on failure.

            Errors:
                Missing file, permission denied, Inkscape not found — check message/error; verify
                allowed_directories and INKSCAPE_PATH.
            """
            return await inkscape_file_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                format=format,
                input_paths=input_paths,
                output_dir=output_dir,
                quality=quality,
                pdf_version=pdf_version,
                pdf_page=pdf_page,
                margin=margin,
                latex=latex,
                ignore_filters=ignore_filters,
                png_color_mode=png_color_mode,
                png_dithering=png_dithering,
                validate_structure=validate_structure,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_vector(
            operation: InkscapeVectorOperation,
            input_path: str = "",
            output_path: str = "",
            object_id: str = "",
            object_ids: list[str] | None = None,
            select_all: bool = False,
            operation_type: str = "",
            barcode_data: str = "",
            source_id: str = "",
            text_id: str = "",
            path_id: str = "",
            output_dir: str = "",
            units: str = "px",
            threshold: float = 1.0,
            offset: float = 1.0,
            dpi: int = 96,
            steps: int = 1,
            rows: int = 3,
            cols: int = 3,
            x_shift: float = 50,
            y_shift: float = 50,
            rotation_step: float = 0.0,
            scale_step: float = 1.0,
            x: float = 300,
            y: float = 200,
            description: str = "",
            trace_scans: int = 4,
            trace_smooth: bool = True,
            trace_stack: bool = True,
            trace_remove_background: bool = False,
            trace_speckles: int = 2,
            trace_smooth_corners: float = 1.0,
            trace_optimize: float = 0.2,
        ) -> dict[str, Any]:
            """INKSCAPE_VECTOR — Vector editing, booleans, trace, QR/barcode, path ops, previews.

            PORTMANTEAU RATIONALE: Inkscape exposes many CLI actions; grouping avoids tool explosion.

            Operations include: trace_image, generate_barcode_qr, apply_boolean, path_simplify,
            optimize_svg, scour_svg, render_preview, query_document, measure_object, export_dxf,
            layers_to_files, object_raise/lower, set_document_units, and others (see Literal).

            Args:
                operation: Subcommand; must match InkscapeVectorOperation.
                input_path: Primary document path.
                output_path: Output file when the operation writes a file.
                object_id: Target element — measure_object, count_nodes, path_simplify,
                    object_raise, object_lower.
                object_ids / select_all: Selection for apply_boolean (supply one or the other).
                    object_ids also scopes align / distribute; omit it to act on everything.
                operation_type: union | difference | intersection | exclusion for apply_boolean.
                    REQUIRED for align — one or two of left|hcenter|right / top|vcenter|bottom
                    plus an optional anchor (last|first|biggest|smallest|page|drawing|selection|pref),
                    e.g. "top", "hcenter vcenter", "top page".
                    REQUIRED for distribute — exactly one of
                    hgap|left|hcenter|right|vgap|top|vcenter|bottom.
                trace_scans, trace_smooth, trace_stack, trace_remove_background, trace_speckles,
                    trace_smooth_corners, trace_optimize: trace_image tuning. Defaults give a
                    4-scan stacked colour trace; raise trace_scans for more colour detail,
                    raise trace_speckles to drop more noise.
                barcode_data: Payload for generate_barcode_qr (required).
                source_id, rows, cols, x_shift, y_shift, rotation_step, scale_step: tile_clone.
                text_id, path_id: text_on_path (both required).
                output_dir: Destination directory for layers_to_files.
                units: Target unit for set_document_units (px, mm, cm, in, pt, pc).
                threshold: Simplification strength for path_simplify (1-10 passes).
                offset: Grow (positive) or shrink (negative) amount for path_inset_outset.
                dpi: Resolution for render_preview. steps: 90-degree turns for page_rotate.
                x, y: Placement for generate_laser_dot. description: title for construct_svg.

            Returns:
                Dict with success, message, data or structured results, execution_time_ms, error.

            Errors:
                Unsupported operation, CLI timeout, invalid paths — use inkscape_system(status)
                and confirm Inkscape install.
            """
            return await inkscape_vector_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                object_id=object_id,
                object_ids=object_ids,
                select_all=select_all,
                operation_type=operation_type,
                barcode_data=barcode_data,
                source_id=source_id,
                text_id=text_id,
                path_id=path_id,
                output_dir=output_dir,
                units=units,
                threshold=threshold,
                offset=offset,
                dpi=dpi,
                steps=steps,
                rows=rows,
                cols=cols,
                x_shift=x_shift,
                y_shift=y_shift,
                rotation_step=rotation_step,
                scale_step=scale_step,
                x=x,
                y=y,
                description=description,
                trace_scans=trace_scans,
                trace_smooth=trace_smooth,
                trace_stack=trace_stack,
                trace_remove_background=trace_remove_background,
                trace_speckles=trace_speckles,
                trace_smooth_corners=trace_smooth_corners,
                trace_optimize=trace_optimize,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_analysis(operation: InkscapeAnalysisOperation, input_path: str) -> dict[str, Any]:
            """INKSCAPE_ANALYSIS — Inspect SVG structure, stats, quality, and dimensions (read-only).

            PORTMANTEAU RATIONALE: Analysis calls are grouped so agents can validate before mutating.

            Operations: quality, statistics, validate, objects, dimensions, structure.

            Args:
                operation: Analysis mode (Literal).
                input_path: SVG file to analyze.

            Returns:
                Dict with success, message, data (bounded per operation), execution_time_ms, error.

            Errors:
                File not found or unreadable SVG — check path and permissions.
            """
            return await inkscape_analysis_tool(
                operation=operation,
                input_path=input_path,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_system(
            operation: InkscapeSystemOperation,
            extension_id: str = "",
            extension_params: dict[str, Any] | None = None,
            input_file: str = "",
            output_file: str = "",
        ) -> dict[str, Any]:
            """INKSCAPE_SYSTEM — Server/Inkscape status, help, diagnostics, version, extensions.

            PORTMANTEAU RATIONALE: Operational and introspection calls stay in one discoverable tool.

            Operations: status, help, diagnostics, version, config, list_extensions, execute_extension.

            Args:
                operation: System subcommand (Literal).
                extension_id: Extension to run for execute_extension (use list_extensions
                    to discover ids). input_file is also required; output_file defaults to
                    overwriting input_file. extension_params carries the extension's own
                    options — call inkscape_extension(describe) for its schema.

            Returns:
                Dict with success, message, data, execution_time_ms, error.

            Errors:
                Inkscape missing, extension disabled — message describes recovery (install PATH).
            """
            return await inkscape_system_tool(
                operation=operation,
                extension_id=extension_id or None,
                extension_params=extension_params,
                input_file=input_file or None,
                output_file=output_file or None,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_gradient(
            operation: InkscapeGradientOperation,
            input_path: str,
            output_path: str,
            gradient_id: str = "",
            stop_offset: str = "",
            stop_color: str = "",
            stop_opacity: float = 1.0,
        ) -> dict[str, Any]:
            """Add/remove/recolor gradient stops; convert linear↔radial (headless — edits a file).

            Preferred over hand-writing gradient SVG for file/headless work. NOT a live tool:
            it reads/writes a file, so for gradients on an OPEN document use `inkscape_live`
            `edit_xml` instead (avoids a reopen).
            """
            return await inkscape_gradient_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                gradient_id=gradient_id,
                stop_offset=stop_offset,
                stop_color=stop_color,
                stop_opacity=stop_opacity,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_metadata(
            operation: InkscapeMetadataOperation,
            input_path: str,
            output_path: str = "",
            value: str = "",
        ) -> dict[str, Any]:
            """Read/write Dublin-Core metadata in the SVG's <rdf:RDF> block."""
            return await inkscape_metadata_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                value=value,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_live(
            operation: InkscapeLiveOperation,
            target: str = "",
            payload: str = "",
            window_id: int = 0,
        ) -> dict[str, Any]:
            """Drive the RUNNING Inkscape GUI — the user's already-open document — live over D-Bus.

            Work on the open document IN PLACE; do not recreate it. Prefer Inkscape's own
            live tools over hand-writing SVG: use `apply_action` for actions and
            `inkscape_extension` `run_live` WITH NO PARAMS for filters/effects like drop
            shadow and blur — select the target first, then call it; that is the only
            run_live mode that sees the live document and selection. (Passing params
            renders on an empty canvas and suits generator extensions only.)
            (The `inkscape_gradient` tool is headless/file-based — not for the live doc.)
            Use `edit_xml` (raw-SVG set_attr/append/insert_*/remove/replace, targeted by
            XPath, multi-node capable) for everything else, e.g. editing gradients on the
            live doc — it is the reliable persisting edit path. `execute_inkex` does NOT
            persist mutations; don't use it to edit.

            Every op acts on Inkscape's ACTIVE document and reports which one that was in
            `data.active_document`. `window_id` cannot route — Inkscape 1.4 has no
            focus-window action — so it is an assertion: leave it at 0 to accept the active
            document, or pass a window number to have the call REFUSE when more than one
            document is open and the target is therefore ambiguous. Check
            `active_document` before any destructive edit; auto-save writes to disk.

            Operations: ping, get_document_xml, get_selection, set_selection, insert_svg,
            delete_selected, apply_action, list_actions, open_file, save_snapshot, edit_xml,
            path_edit, inspect_selection/layers/defs/view/pages/element, execute_inkex,
            rasterize.
            """
            return await inkscape_live_tool(
                operation=operation,
                target=target,
                payload=payload,
                window_id=window_id,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_extension(
            operation: InkscapeExtensionOperation,
            target: str = "",
            params: str = "",
            input_path: str = "",
            output_path: str = "",
            wrapper_id: str = "",
        ) -> dict[str, Any]:
            """Discover and invoke any installed Inkscape extension with custom params.

            Operations:
              - list: discover all installed extensions (target = optional substring filter)
              - describe: full param schema for one extension (target = extension id)
              - run: invoke headlessly on a file (target + params JSON + input_path [+ output_path])
              - run_live: invoke on the running Inkscape doc (target + params JSON). Pass
                          `wrapper_id` to re-render in place — any prior element with that id
                          is removed first so CSS rules / style hooks keep targeting it.
            """
            return await inkscape_extension_tool(
                operation=operation,
                target=target,
                params=params,
                input_path=input_path,
                output_path=output_path,
                wrapper_id=wrapper_id,
            )

        self.tools = {
            "inkscape_file": inkscape_file,
            "inkscape_vector": inkscape_vector,
            "inkscape_analysis": inkscape_analysis,
            "inkscape_system": inkscape_system,
            "inkscape_extension": inkscape_extension,
        }


async def main_async() -> int:
    """Async entry point."""
    # Configure basic logging first
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Inkscape MCP Server")
    parser.add_argument("--config", type=str, help="Path to config file", default=None)
    # default=None (not "stdio") so we can tell "flag omitted" from "explicitly --mode=stdio"
    # without string-matching sys.argv, which missed the --mode=http spelling.
    parser.add_argument("--mode", choices=["stdio", "http"], default=None)
    parser.add_argument(
        "--port",
        type=int,
        default=10847,
        help="HTTP port when MCP-streamable HTTP transport is used (path /mcp).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    # Re-setup logging with arg level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, force=True)

    # Bridge this CLI to transport env.
    # If MCP_TRANSPORT is already set externally (e.g. Claude Desktop config env),
    # honour it — only apply the argparser value when --mode was explicitly passed.
    if args.mode is not None:
        os.environ["MCP_PORT"] = str(args.port)
        os.environ["MCP_TRANSPORT"] = args.mode
        os.environ["MCP_HOST"] = args.host
    else:
        if not os.environ.get("MCP_TRANSPORT"):
            os.environ["MCP_TRANSPORT"] = "stdio"
        os.environ.setdefault("MCP_PORT", str(args.port))
        os.environ.setdefault("MCP_HOST", args.host)

    # Hand the transport layer an already-parsed namespace. Left to itself it builds a
    # different parser (--stdio/--http/--sse/...) and re-parses sys.argv, so any flag
    # accepted above ("--mode stdio", "--log-level DEBUG") aborted the server with
    # "unrecognized arguments" *after* a full initialization — and SystemExit, being a
    # BaseException, slipped straight past the `except Exception` below.
    transport_args = argparse.Namespace(
        stdio=(args.mode == "stdio"),
        http=(args.mode == "http"),
        sse=False,
        host=args.host,
        port=args.port,
        path=None,
        debug=(log_level <= logging.DEBUG),
    )

    try:
        server = InkscapeMCPServer(config_path=Path(args.config) if args.config else None)
        if await server.initialize():
            await run_server_async(server.mcp, args=transport_args, server_name="Inkscape MCP Server")
        else:
            return 1
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Server error:")
        return 1

    return 0


def main() -> int:
    """Main entry point."""
    try:
        return asyncio.run(main_async())
    except Exception as e:
        print(f"Unhandled error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
