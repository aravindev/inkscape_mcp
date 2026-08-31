"""Comprehensive file operations for Inkscape SVG documents.

PORTMANTEAU PATTERN RATIONALE:
Consolidates 6 file operations into single interface. Prevents tool explosion while maintaining
full functionality and improving discoverability. Follows FastMCP 2.14.1+ SOTA standards.

SUPPORTED OPERATIONS:
- load: Load and validate SVG files
- save: Save SVG files with formatting options
- convert: Convert between vector formats
- info: Get comprehensive file metadata and statistics
- validate: Validate SVG structure and syntax
- list_formats: Enumerate all supported export formats

OPERATIONS DETAIL:

**File Management (CRUD)**:
  - load: Validates SVG syntax and basic structure, returns dimensions and file metadata
  - save: Writes SVG with optional formatting and structure validation
  - convert: Transforms between vector formats using Inkscape export functionality

**Analysis & Discovery**:
  - info: Extracts dimensions, file size, format, and comprehensive metadata
  - validate: Checks SVG validity using Inkscape query commands, reports issues
  - list_formats: Shows all available export formats supported by Inkscape

Args:
    operation (Literal, required): The file operation to perform. Must be one of:
        "load", "save", "convert", "info", "validate", "list_formats".
        - "load": Load SVG file and validate structure (requires: input_path)
        - "save": Save SVG with options (requires: input_path, output_path)
        - "convert": Convert between formats (requires: input_path, output_path, format)
        - "info": Get file metadata (requires: input_path)
        - "validate": Validate SVG structure (requires: input_path)
        - "list_formats": List supported formats (no additional parameters required)

    input_path (str | None): Path to input SVG file. Required for: load, save, convert, info,
        validate operations.
        Must be a valid file path accessible by the system.

    output_path (str | None): Path for output file. Required for: save, convert operations.
        Directory must exist and be writable. File extension should match format parameter.

    format (str | None): Output format for convert operations. Must be one of:
        "pdf", "eps", "ai", "cdr", "svg", "png", "ps", "wmf", "emf", "xaml".
        Required for: convert operation. Case-insensitive.

    validate_structure (bool): Whether to validate SVG structure during load operations.
        Default: True. When True, uses Inkscape query commands to verify file validity.

    cli_wrapper (Any): Injected CLI wrapper dependency. Required. Handles Inkscape command
        execution.

    config (Any): Injected configuration dependency. Required. Contains Inkscape executable path
        and settings.

Returns:
    FastMCP 2.14.1+ Enhanced Response Pattern with success/error states, execution timing,
    next steps, and recovery options for failed operations.

Examples:
    # Load and validate an SVG file
    result = await inkscape_file(
        operation="load",
        input_path="drawing.svg"
    )

    # Convert SVG to PDF
    result = await inkscape_file(
        operation="convert",
        input_path="drawing.svg",
        output_path="drawing.pdf",
        format="pdf"
    )

    # Get file information
    result = await inkscape_file(
        operation="info",
        input_path="drawing.svg"
    )
      "diagnostic_info": {
        "file_exists": false,
        "inkscape_available": true,
        "permissions": "read-only"
      },
      "alternative_solutions": ["Use list_formats to verify supported formats",
        "Check file extension matches format"]
    }

Examples:
    # Load and validate an SVG file
    result = await inkscape_file(
        operation="load",
        input_path="logo.svg",
        validate_structure=True
    )

    # Convert SVG to PDF
    result = await inkscape_file(
        operation="convert",
        input_path="drawing.svg",
        output_path="drawing.pdf",
        format="pdf"
    )

    # Get comprehensive file information
    result = await inkscape_file(
        operation="info",
        input_path="design.svg"
    )

    # Validate SVG structure
    result = await inkscape_file(
        operation="validate",
        input_path="document.svg"
    )

    # List all supported export formats
    result = await inkscape_file(
        operation="list_formats"
    )

    # Save SVG with formatting
    result = await inkscape_file(
        operation="save",
        input_path="source.svg",
        output_path="formatted.svg"
    )

Errors:
    - FileNotFoundError: Input file does not exist or is not readable
        Recovery options:
        - Verify file path is correct and accessible
        - Check file permissions (read access required)
        - Ensure file is a valid SVG document
        - Use absolute paths if relative paths fail

    - InkscapeExecutionError: Inkscape CLI command failed
        Recovery options:
        - Verify Inkscape installation (run inkscape --version)
        - Check CLI arguments are valid for Inkscape version
        - Ensure output directory exists and is writable
        - Check process timeout settings in config

    - ValueError: Invalid format or parameters
        Recovery options:
        - Verify format is supported (use list_formats operation)
        - Check output_path is provided for write operations (save, convert)
        - Ensure format parameter matches file extension
        - Validate all required parameters are provided

    - PermissionError: Cannot write to output location
        Recovery options:
        - Check write permissions on output directory
        - Ensure output path is not read-only
        - Verify sufficient disk space available
        - Check if file is locked by another process
"""

import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .dimensions import size_report

# Formats Inkscape cannot export natively — we pipe through Pillow.
_PILLOW_FORMATS = {"jpeg", "jpg", "webp", "avif"}


async def _convert_via_pillow(
    input_path: str,
    output_path: str,
    fmt: str,
    quality: int,
    cli_wrapper: Any,
    config: Any,
) -> None:
    """Render input to a temp PNG via Inkscape, then re-encode with Pillow."""
    from PIL import Image

    if fmt == "avif":
        try:
            import pillow_avif  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "AVIF support requires 'pillow-avif-plugin'. Install it with: pip install pillow-avif-plugin"
            ) from exc

    pil_format = {"jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "avif": "AVIF"}[fmt]

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_png = tmp.name
    try:
        actions = _build_convert_actions(output_path=tmp_png, format="png")
        await cli_wrapper._execute_actions(
            input_path=input_path,
            actions=actions,
            output_path=tmp_png,
            timeout=config.process_timeout,
        )
        with Image.open(tmp_png) as img:
            out: Image.Image = img
            if pil_format == "JPEG":
                # JPEG has no alpha channel.
                out = img.convert("RGB")
                out.save(output_path, format="JPEG", quality=quality, optimize=True)
            elif pil_format == "WEBP":
                # Preserve alpha if present.
                if img.mode not in ("RGB", "RGBA"):
                    out = img.convert("RGBA" if "A" in img.mode else "RGB")
                out.save(output_path, format="WEBP", quality=quality)
            else:  # AVIF
                if img.mode not in ("RGB", "RGBA"):
                    out = img.convert("RGBA" if "A" in img.mode else "RGB")
                out.save(output_path, format="AVIF", quality=quality)
    finally:
        try:
            Path(tmp_png).unlink()
        except OSError:
            pass


class FileOperationResult(BaseModel):
    """Result model for file operations."""

    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


def _build_convert_actions(
    output_path: str,
    format: str,
    pdf_version: str = "",
    margin: float = 0,
    latex: bool = False,
    ignore_filters: bool = False,
    png_color_mode: str = "",
    png_dithering: bool = False,
) -> list[str]:
    # Inkscape 1.4 accepts lowercase export-type values directly (png, pdf, ps, eps, emf, wmf, xaml, svg).
    actions = [f"export-filename:{output_path}", f"export-type:{format.lower()}"]
    if pdf_version:
        actions.append(f"export-pdf-version:{pdf_version}")
    if margin:
        actions.append(f"export-margin:{margin}")
    if latex:
        actions.append("export-latex")
    if ignore_filters:
        actions.append("export-ignore-filters")
    if png_color_mode:
        actions.append(f"export-png-color-mode:{png_color_mode}")
    if png_dithering:
        actions.append("export-png-use-dithering")
    actions.append("export-do")
    return actions


async def inkscape_file(
    operation: Literal["load", "save", "convert", "info", "validate", "list_formats", "batch_convert"],
    input_path: str = "",
    output_path: str = "",
    format: str = "",
    validate_structure: bool = True,
    pdf_version: str = "",
    margin: float = 0,
    latex: bool = False,
    ignore_filters: bool = False,
    png_color_mode: str = "",
    png_dithering: bool = False,
    pdf_page: int = 1,
    input_paths: list[str] | None = None,
    output_dir: str = "",
    quality: int = 90,
    cli_wrapper: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """Inkscape file operations portmanteau tool."""
    start_time = time.time()

    try:
        input_path_obj = Path(input_path)

        if operation == "load":
            # Basic load and validate
            if not input_path_obj.exists():
                return FileOperationResult(
                    success=False,
                    operation="load",
                    message=f"File not found: {input_path}",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error="FileNotFoundError",
                ).model_dump()

            # Use Inkscape to validate by attempting to query dimensions
            try:
                cmd = [str(config.inkscape_executable), "--app-id-tag=mcp"]
                if input_path_obj.suffix.lower() == ".pdf":
                    cmd.append(f"--pdf-page={pdf_page}")
                cmd.extend([str(input_path_obj), "--query-width"])
                result = await cli_wrapper._execute_command(cmd, config.process_timeout)
                width = float(result.strip())

                return FileOperationResult(
                    success=True,
                    operation="load",
                    message=f"Successfully loaded {input_path}",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "width": width,
                        "loaded": True,
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return FileOperationResult(
                    success=False,
                    operation="load",
                    message=f"Failed to load SVG: {e}",
                    data={"path": str(input_path_obj)},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "convert":
            if not output_path:
                return FileOperationResult(
                    success=False,
                    operation="convert",
                    message="Output path required for convert operation",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error="ValueError",
                ).model_dump()

            # Inkscape can't write JPEG/WebP/AVIF directly — round-trip through Pillow.
            fmt_lower = format.lower()
            if fmt_lower in _PILLOW_FORMATS:
                try:
                    await _convert_via_pillow(
                        input_path=input_path,
                        output_path=output_path,
                        fmt=fmt_lower,
                        quality=quality,
                        cli_wrapper=cli_wrapper,
                        config=config,
                    )
                    return FileOperationResult(
                        success=True,
                        operation="convert",
                        message=f"Converted {input_path} to {output_path}",
                        data={
                            "input_path": str(input_path_obj.resolve()),
                            "output_path": output_path,
                            "format": fmt_lower,
                            "quality": quality,
                        },
                        execution_time_ms=(time.time() - start_time) * 1000,
                    ).model_dump()
                except Exception as e:
                    return FileOperationResult(
                        success=False,
                        operation="convert",
                        message=f"Conversion failed: {e}",
                        data={},
                        execution_time_ms=(time.time() - start_time) * 1000,
                        error=str(e),
                    ).model_dump()

            actions = _build_convert_actions(
                output_path=output_path,
                format=format,
                pdf_version=pdf_version,
                margin=margin,
                latex=latex,
                ignore_filters=ignore_filters,
                png_color_mode=png_color_mode,
                png_dithering=png_dithering,
            )

            try:
                await cli_wrapper._execute_actions(
                    input_path=input_path,
                    actions=actions,
                    output_path=output_path,
                    timeout=config.process_timeout,
                )

                return FileOperationResult(
                    success=True,
                    operation="convert",
                    message=f"Converted {input_path} to {output_path}",
                    data={
                        "input_path": str(input_path_obj.resolve()),
                        "output_path": output_path,
                        "format": format,
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return FileOperationResult(
                    success=False,
                    operation="convert",
                    message=f"Conversion failed: {e}",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "batch_convert":
            paths = input_paths or []
            if not paths or not output_dir or not format:
                return FileOperationResult(
                    success=False,
                    operation="batch_convert",
                    message="batch_convert requires input_paths, output_dir, and format",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error="ValueError",
                ).model_dump()

            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            results: list[dict[str, Any]] = []
            success_count = 0

            for src in paths:
                src_path = Path(src)
                dst = out_dir / f"{src_path.stem}.{format.lower()}"
                actions = _build_convert_actions(
                    output_path=str(dst),
                    format=format,
                    pdf_version=pdf_version,
                    margin=margin,
                    latex=latex,
                    ignore_filters=ignore_filters,
                    png_color_mode=png_color_mode,
                    png_dithering=png_dithering,
                )
                try:
                    await cli_wrapper._execute_actions(
                        input_path=str(src_path),
                        actions=actions,
                        output_path=str(dst),
                        timeout=config.process_timeout,
                    )
                    results.append({"success": True, "output_path": str(dst), "error": ""})
                    success_count += 1
                except Exception as e:
                    results.append({"success": False, "output_path": str(dst), "error": str(e)})

            return FileOperationResult(
                success=success_count == len(paths),
                operation="batch_convert",
                message=f"Converted {success_count}/{len(paths)} files",
                data={
                    "results": results,
                    "total": len(paths),
                    "succeeded": success_count,
                    "failed": len(paths) - success_count,
                    "output_dir": str(out_dir.resolve()),
                    "format": format,
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "info":
            # Get basic file info
            if not input_path_obj.exists():
                return FileOperationResult(
                    success=False,
                    operation="info",
                    message=f"File not found: {input_path}",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error="FileNotFoundError",
                ).model_dump()

            try:
                # `width`/`height` here used to be the drawing bounding box while
                # `analysis statistics` used the same names for the page size. Both are
                # now reported under names that say which is which.
                report = await size_report(input_path_obj, cli_wrapper, config)

                return FileOperationResult(
                    success=True,
                    operation="info",
                    message=f"Retrieved info for {input_path}",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "file_size": input_path_obj.stat().st_size,
                        **report,
                        "format": "svg",
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return FileOperationResult(
                    success=False,
                    operation="info",
                    message=f"Failed to get info: {e}",
                    data={"path": str(input_path_obj)},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "validate":
            # Basic validation by attempting to load
            try:
                result = await cli_wrapper._execute_command(
                    [
                        str(config.inkscape_executable),
                        "--app-id-tag=mcp",
                        str(input_path_obj),
                        "--query-width",
                    ],
                    config.process_timeout,
                )

                return FileOperationResult(
                    success=True,
                    operation="validate",
                    message="SVG is valid",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "valid": True,
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            except Exception as e:
                return FileOperationResult(
                    success=False,
                    operation="validate",
                    message=f"SVG validation failed: {e}",
                    data={
                        "path": str(input_path_obj.resolve()),
                        "valid": False,
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "save":
            # Save = copy input → output, validating the SVG round-trips through Inkscape.
            if not output_path:
                return FileOperationResult(
                    success=False,
                    operation="save",
                    message="Output path required for save operation",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error="ValueError",
                ).model_dump()
            try:
                actions = [f"export-filename:{output_path}", "export-type:svg", "export-do"]
                await cli_wrapper._execute_actions(
                    input_path=input_path,
                    actions=actions,
                    output_path=output_path,
                    timeout=config.process_timeout,
                )
                return FileOperationResult(
                    success=True,
                    operation="save",
                    message=f"Saved {input_path} to {output_path}",
                    data={"input_path": str(input_path_obj.resolve()), "output_path": output_path},
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()
            except Exception as e:
                return FileOperationResult(
                    success=False,
                    operation="save",
                    message=f"Save failed: {e}",
                    data={},
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                ).model_dump()

        elif operation == "list_formats":
            # List supported export formats
            formats = ["svg", "pdf", "eps", "png", "ps", "ai", "cdr", "wmf", "emf", "xaml"]

            return FileOperationResult(
                success=True,
                operation="list_formats",
                message="Retrieved supported formats",
                data={"formats": formats},
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        else:
            # Defensive: unreachable for a well-typed caller, but the tools are also
            # invoked directly (tests, other tools) where `operation` is just a str.
            return FileOperationResult(  # type: ignore[unreachable]
                success=False,
                operation=operation,
                message=f"Unknown operation: {operation}",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="ValueError",
            ).model_dump()

    except Exception as e:
        return FileOperationResult(
            success=False,
            operation=operation,
            message=f"Operation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        ).model_dump()
