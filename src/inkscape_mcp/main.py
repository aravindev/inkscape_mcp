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
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import InkscapeConfig, load_config
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
window (the `inkscape_live` tool, over D-Bus). Default working style:

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

3. For live structural edits, `edit_xml` is the reliable, persisting path: it targets
   nodes by XPath and saves in place. `set_attr`/`remove` accept a multi-node XPath
   (e.g. `//*[@id='g']/*[position()>9]`). Note: `execute_inkex` does not currently persist
   document mutations — do not rely on it for edits.

4. On Wayland without `wl-clipboard`, clipboard-based `insert_svg` is unavailable; insert
   content with `edit_xml` `append` instead.
"""


class InkscapeMCPServer:
    """Main server class for Inkscape MCP integration."""

    def __init__(self, config_path: Path | None = None):
        """Initialize the Inkscape MCP Server.

        Args:
            config_path: Optional path to configuration file
        """
        self.config = load_config(config_path) if config_path else InkscapeConfig()
        self.mcp = FastMCP("Inkscape MCP Server", instructions=SERVER_INSTRUCTIONS)
        self.tools = {}
        self.logger = logging.getLogger(__name__)
        self.cli_wrapper: Any | None = None

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

            # Initialize Inkscape detector
            self.inkscape_detector = InkscapeDetector()
            inkscape_path = self.inkscape_detector.detect_inkscape_installation()

            if inkscape_path:
                logger.info(f"Found Inkscape at: {inkscape_path}")
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

            try:
                register_prompts_and_resources(self.mcp)
                logger.info("MCP prompts and resources registered")
            except Exception as e:
                logger.warning("Failed to register prompts/resources: %s", e)

            try:
                from .extension_bridge import install_plugins

                install_result = install_plugins()
                if install_result.get("action") == "copied":
                    logger.info(
                        "Extension bridge: installed %d plugin(s); Inkscape restart required",
                        len(install_result.get("files", [])),
                    )
                else:
                    logger.info("Extension bridge: plugins up to date (v%s)", install_result.get("version"))
            except Exception as e:
                logger.warning("Extension bridge install failed (continuing): %s", e)

            # Register Prefab UI (FastMCP 3.2 GenerativeUI)
            if PREFAB_AVAILABLE and register_prefabs:
                try:
                    register_prefabs(self.mcp)
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
                input_path: Source file; may be empty for list_formats only.
                output_path: Destination for save/convert when applicable.
                format: Target format for convert (e.g. pdf, png).

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
        ) -> dict[str, Any]:
            """INKSCAPE_VECTOR — Vector editing, booleans, trace, QR/barcode, path ops, previews.

            PORTMANTEAU RATIONALE: Inkscape exposes many CLI actions; grouping avoids tool explosion.

            Operations include: trace_image, generate_barcode_qr, apply_boolean, path_simplify,
            optimize_svg, scour_svg, render_preview, query_document, measure_object, export_dxf,
            layers_to_files, object_raise/lower, set_document_units, and others (see Literal).

            Args:
                operation: Subcommand; must match InkscapeVectorOperation.
                input_path: Primary document path (some ops may use output-only paths in kwargs).
                output_path: Output file when the operation writes a file.

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
        async def inkscape_system(operation: InkscapeSystemOperation) -> dict[str, Any]:
            """INKSCAPE_SYSTEM — Server/Inkscape status, help, diagnostics, version, extensions.

            PORTMANTEAU RATIONALE: Operational and introspection calls stay in one discoverable tool.

            Operations: status, help, diagnostics, version, config, list_extensions, execute_extension.

            Args:
                operation: System subcommand (Literal). Extension execution may require extra
                    parameters not exposed on this MCP wrapper — prefer list_extensions first.

            Returns:
                Dict with success, message, data, execution_time_ms, error.

            Errors:
                Inkscape missing, extension disabled — message describes recovery (install PATH).
            """
            return await inkscape_system_tool(
                operation=operation,
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
            window_id: int = 1,
        ) -> dict[str, Any]:
            """Drive the RUNNING Inkscape GUI — the user's already-open document — live over D-Bus.

            Work on the open document IN PLACE; do not recreate it. Prefer Inkscape's own
            live tools over hand-writing SVG: use `apply_action` for actions and
            `inkscape_extension` `run_live` for filters/effects like drop shadow and blur.
            (The `inkscape_gradient` tool is headless/file-based — not for the live doc.)
            Use `edit_xml` (raw-SVG set_attr/append/insert_*/remove/replace, targeted by
            XPath, multi-node capable) for everything else, e.g. editing gradients on the
            live doc — it is the reliable persisting edit path. `execute_inkex` does NOT
            persist mutations; don't use it to edit.

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


async def main_async():
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
    parser.add_argument("--mode", choices=["stdio", "http"], default="stdio")
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
    log_level = getattr(logging, args.log_level.upper())
    logging.basicConfig(level=log_level, force=True)

    # Bridge this CLI to transport env.
    # If MCP_TRANSPORT is already set externally (e.g. Claude Desktop config env),
    # honour it — only apply the argparser value when --mode was explicitly passed.
    explicit_mode = "--mode" in sys.argv
    if explicit_mode:
        os.environ["MCP_PORT"] = str(args.port)
        os.environ["MCP_TRANSPORT"] = args.mode
    else:
        if not os.environ.get("MCP_TRANSPORT"):
            os.environ["MCP_TRANSPORT"] = "stdio"
        os.environ.setdefault("MCP_PORT", str(args.port))

    try:
        server = InkscapeMCPServer(config_path=Path(args.config) if args.config else None)
        if await server.initialize():
            await run_server_async(server.mcp, server_name="Inkscape MCP Server")
        else:
            return 1
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Server error:")
        return 1

    return 0


def main():
    """Main entry point."""
    try:
        return asyncio.run(main_async())
    except Exception as e:
        print(f"Unhandled error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
