"""FastMCP 3.1+ prompts and resources for inkscape_mcp (fleet SOTA alignment).

Registers MCP prompts (prompt://inkscape/...) and resources (resource://inkscape/...)
so clients that list prompts/resources see real entries, not only MCPB bundle text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts_and_resources(mcp: FastMCP) -> None:
    """Attach prompts and resources to the given FastMCP instance."""

    @mcp.prompt("prompt://inkscape/svg-file-workflow")
    def prompt_svg_file_workflow() -> str:
        """Guide file-level SVG workflows (load, convert, validate)."""
        return """Guide the user through Inkscape MCP file operations.
1. Call inkscape_system(operation="status") or operation="version" to confirm Inkscape is reachable.
2. Use inkscape_file(operation="info", input_path="...") for format and basic metadata.
3. Use inkscape_file(operation="validate", input_path="...") before heavy edits.
4. Use inkscape_file(operation="convert", input_path="...", output_path="...", format="pdf|png|...") for exports.
5. Prefer absolute paths the server is allowed to read; respect allowed_directories in config."""

    @mcp.prompt("prompt://inkscape/vector-editing-workflow")
    def prompt_vector_editing_workflow() -> str:
        """Guide vector edits via inkscape_vector."""
        return """Guide vector editing with inkscape_vector (Inkscape CLI --actions).
1. Start from inkscape_analysis(operation="dimensions", input_path="...") or "statistics" for context.
2. Typical flows: path_simplify, path_clean, apply_boolean (union/intersect), trace_image for rasters.
3. Barcodes/QR: inkscape_vector(operation="generate_barcode_qr", output_path="...", barcode_data="...").
4. Always pass input_path and output_path when the operation writes a file; verify success in the response dict."""

    @mcp.prompt("prompt://inkscape/analysis-workflow")
    def prompt_analysis_workflow() -> str:
        """Guide document analysis before editing."""
        return """Use inkscape_analysis to understand an SVG before changing it.
1. inkscape_analysis(operation="statistics", input_path="...")
2. inkscape_analysis(operation="objects", input_path="...") for structure
3. inkscape_analysis(operation="validate", input_path="...")
4. inkscape_analysis(operation="dimensions", input_path="...")
5. Summarize findings and propose the smallest set of inkscape_vector / inkscape_file calls to meet the user goal."""

    @mcp.resource("resource://inkscape/capabilities")
    def resource_capabilities() -> str:
        """Static capability summary for indexers and clients."""
        return """inkscape_mcp (FastMCP 3.2+)

Broad primitives:
  inkscape_live       — drive a running Inkscape via D-Bus (apply_action, edit_xml, insert_svg,
                        path_edit, inspect_* family, get_selection, list_actions [filtered], ...)
  inkscape_extension  — discover / describe / run any installed Inkscape extension with custom params
                        (list, describe, run, run_live)
  inkscape_file       — load / save / convert / info / validate / list_formats
  inkscape_vector     — 22 vector ops (trace, boolean, path simplify, etc.)
  inkscape_analysis   — quality / statistics / validate / objects / dimensions / structure
  inkscape_system     — status / help / diagnostics / version / config

Convenience tools (unique XML logic):
  inkscape_gradient   — gradient stops (add / remove / set color / convert linear↔radial / list)
  inkscape_metadata   — Dublin-Core RDF metadata (title / creator / description / rights / keywords)

Prompts: prompt://inkscape/svg-file-workflow, vector-editing-workflow, analysis-workflow

Resources: resource://inkscape/capabilities, resource://inkscape/skills,
  resource://inkscape/mcp-workflow, resource://inkscape/cli-actions, resource://inkscape/cli-help"""

    @mcp.resource("resource://inkscape/skills")
    def resource_skills() -> str:
        """LLM-oriented skill reference loaded from skills/SKILL.md (CodeMode discovery)."""
        from pathlib import Path

        skill_path = Path(__file__).parent / "skills" / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        return "Skills file not found — expected at src/inkscape_mcp/skills/SKILL.md"

    # ---------------------------------------------------------------------
    # Documentation resources — exposes the bundled reference files so agents
    # can fetch the operational guide + Inkscape's full CLI surface without
    # shelling out themselves.
    # ---------------------------------------------------------------------

    def _read_docs_reference(filename: str, friendly_name: str) -> str:
        # These live inside the package (like skills/) so they ship in the wheel.
        # Resolving them relative to the repo root worked only from a git checkout:
        # from site-packages it pointed outside the install and every one of these
        # resources reported "not found" for PyPI users.
        from importlib import resources

        try:
            return (resources.files("inkscape_mcp.reference") / filename).read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            return f"{friendly_name} not found — expected at inkscape_mcp/reference/{filename}"

    @mcp.resource("resource://inkscape/mcp-workflow")
    def resource_mcp_workflow() -> str:
        """Operational guide — picking the right op, gotchas, recipes, Inkscape rendering pitfalls.

        Sourced from the bundled reference/mcp-workflow.md. Read this first when working
        out which MCP call covers a desired Inkscape operation."""
        return _read_docs_reference("mcp-workflow.md", "MCP workflow guide")

    @mcp.resource("resource://inkscape/cli-actions")
    def resource_cli_actions() -> str:
        """Full output of `inkscape --action-list` — every D-Bus-reachable verb with a one-line
        description. Use this as the catalog when `list_actions(target=...)` filter isn't enough,
        or when you want to browse the entire surface."""
        return _read_docs_reference("inkscape-1.4.4-actions.txt", "Inkscape action list")

    @mcp.resource("resource://inkscape/cli-help")
    def resource_cli_help() -> str:
        """Full output of `inkscape --help` — CLI flags for headless invocation
        (--export-type, --actions, --shell, --batch-process, etc.)."""
        return _read_docs_reference("inkscape-1.4.4-help.txt", "Inkscape CLI help")
