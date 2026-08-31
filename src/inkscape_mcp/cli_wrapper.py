"""
Minimal Inkscape CLI Wrapper for essential vector graphics operations.

This module provides core Inkscape command-line functionality for MCP operations.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Inkscape 1.4 writes per-action failures to stderr and still exits 0. Each of these
# means the action ran as a no-op, so the export comes out unmodified while every
# other signal says "success".
_ACTION_ERROR_PATTERNS = (
    # action:object_trace: expected argument format: {scans},{smooth},...
    re.compile(r"^action:\S+:\s*expected argument format:.*$", re.MULTILINE),
    # action:object_trace: parsing arguments failed: stod
    re.compile(r"^action:\S+:\s*parsing arguments failed:.*$", re.MULTILINE),
    # select_by_id: Did not find object with id: nope
    re.compile(r"^\s*select_by_id:\s*Did not find object with id:.*$", re.MULTILINE),
)


def _find_action_error(stderr_text: str) -> str:
    """Return the first action-level failure in `stderr_text`, or "" if it is clean."""
    if not stderr_text:
        return ""
    for pattern in _ACTION_ERROR_PATTERNS:
        if match := pattern.search(stderr_text):
            return match.group(0).strip()
    return ""


class InkscapeCliError(Exception):
    """Base exception for Inkscape CLI operations."""

    pass


class InkscapeTimeoutError(InkscapeCliError):
    """Exception for Inkscape operation timeouts."""

    pass


class InkscapeExecutionError(InkscapeCliError):
    """Exception for Inkscape execution failures."""

    pass


class InkscapeCliWrapper:
    """
    Minimal Inkscape CLI wrapper for essential vector graphics operations.
    """

    def __init__(self, config: Any) -> None:
        """
        Initialize wrapper with config.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Basic validation
        if not hasattr(config, "inkscape_executable") or not config.inkscape_executable:
            raise InkscapeCliError("Inkscape executable not configured")

        if not Path(config.inkscape_executable).exists():
            raise InkscapeCliError(f"Inkscape executable not found: {config.inkscape_executable}")

    def _base_cmd(self) -> list[str]:
        # --app-id-tag picks a distinct D-Bus name so this subprocess doesn't collide
        # with a GUI instance that already owns org.inkscape.Inkscape.
        return [self.config.inkscape_executable, "--app-id-tag=mcp"]

    async def export_file(
        self,
        input_path: str,
        output_path: str,
        export_type: str = "png",
        dpi: int = 300,
        export_area: str = "drawing",
        timeout: int | None = None,
    ) -> str:
        """
        Export SVG file to raster or vector format using Inkscape CLI.

        Args:
            input_path: Input SVG file path
            output_path: Output file path
            export_type: Export format (png, pdf, eps, svg)
            dpi: Resolution for raster exports (ignored for vector formats)
            export_area: Export area (drawing, page, or custom coordinates)
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = timeout or self.config.process_timeout

        cmd_args = [
            *self._base_cmd(),
            "--export-type",
            export_type,
            "--export-filename",
            output_path,
        ]

        # Add DPI for raster formats
        if export_type.lower() in ["png", "jpg", "jpeg", "tiff", "bmp"]:
            cmd_args.extend(["--export-dpi", str(dpi)])

        # Add export area
        if export_area == "drawing":
            cmd_args.append("--export-area-drawing")
        elif export_area == "page":
            cmd_args.append("--export-area-page")
        elif export_area.startswith("custom:"):
            # Custom coordinates: "custom:x0:y0:x1:y1"
            coords = export_area.split(":", 1)[1]
            cmd_args.extend(["--export-area", coords])

        # Add input file
        cmd_args.append(input_path)

        return await self._execute_command(cmd_args, timeout)

    async def query_object(
        self,
        input_path: str,
        object_id: str,
        query_type: str = "bbox",
        timeout: int | None = None,
    ) -> str:
        """
        Query object properties from SVG file using Inkscape CLI.

        Args:
            input_path: Input SVG file path
            object_id: ID of object to query
            query_type: Type of query (bbox, x, y, width, height, all)
            timeout: Operation timeout in seconds

        Returns:
            str: Query result output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = timeout or self.config.process_timeout

        # Build command arguments
        cmd_args = [*self._base_cmd(), "--query-id", object_id]

        # Add specific query type
        if query_type == "bbox":
            cmd_args.append("--query-bbox")
        elif query_type == "x":
            cmd_args.append("--query-x")
        elif query_type == "y":
            cmd_args.append("--query-y")
        elif query_type == "width":
            cmd_args.append("--query-width")
        elif query_type == "height":
            cmd_args.append("--query-height")
        elif query_type == "all":
            # Query all properties
            pass

        # Add input file
        cmd_args.append(input_path)

        return await self._execute_command(cmd_args, timeout)

    async def execute_verbs(
        self,
        input_path: str,
        verbs: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """
        Execute Inkscape verbs (actions) on an SVG file.

        Args:
            input_path: Input SVG file path
            verbs: List of Inkscape verb IDs to execute
            output_path: Optional output path (will overwrite input if None)
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = timeout or self.config.process_timeout

        # 1.4 dropped --batch-process; --export-* flags or --actions trigger headless export.
        cmd_args = self._base_cmd()

        for verb in verbs:
            cmd_args.extend(["--verb", verb])

        # Add output if specified
        if output_path:
            cmd_args.extend(["--export-filename", output_path])

        # Add input file
        cmd_args.append(input_path)

        return await self._execute_command(cmd_args, timeout)

    async def _execute_actions(
        self,
        input_path: str,
        actions: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """
        Execute Inkscape actions using the --actions flag.

        Args:
            input_path: Input SVG file path
            actions: List of Inkscape action IDs to execute
            output_path: Optional output path
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = timeout or self.config.process_timeout

        # A bare string here would be splatted character-by-character by the join below
        # (`"a;b"` -> `a;;;b`). Inkscape then rejects every character, exits 0 anyway, and
        # the export silently comes out unmodified. Callers pass this in as `Any`, so
        # neither ruff nor mypy can catch it — fail loudly instead.
        if isinstance(actions, str):  # type: ignore[unreachable]
            raise TypeError(f"actions must be a list of action strings, got str: {actions!r}")

        cmd_args = self._base_cmd()

        # Build the complete action chain BEFORE rendering the flag: the export action has
        # to end up inside --actions=, not tacked onto whatever argv element happens to be
        # last (which was --export-filename, producing "Unknown export type: svg;export-do").
        chain = list(actions)
        if output_path and not any(a == "export-do" or a.startswith("export-do:") for a in chain):
            chain.append("export-do")
        actions_str = ";".join(chain)

        # Add input file
        cmd_args.append(str(Path(input_path).resolve()))

        # Add the actions flag
        cmd_args.append(f"--actions={actions_str}")

        if output_path:
            cmd_args.append(f"--export-filename={Path(output_path).resolve()!s}")

        result, stderr_text = await self._execute_command_capture(cmd_args, timeout)

        # Inkscape reports per-action failures on stderr and still exits 0, so a bad action
        # chain looks identical to a good one: the export is written, just unmodified. That
        # made `object-trace`/`object-align`/`object-distribute` fired without their required
        # argument silently return "success" on an untouched file. Fail loudly instead.
        if action_error := _find_action_error(stderr_text):
            raise InkscapeExecutionError(f"Inkscape rejected an action: {action_error} | actions: {actions_str}")

        # Inkscape can exit 0 without producing the requested output (e.g. unknown action,
        # mistyped format). Treat a missing/empty output file as a hard failure.
        if output_path:
            out = Path(output_path)
            if not out.exists() or out.stat().st_size == 0:
                raise InkscapeExecutionError(
                    f"Inkscape returned success but did not write {output_path}. "
                    f"Command: {' '.join(cmd_args)} | stdout: {result[:400]}"
                )
        return result

    async def execute_actions(
        self,
        input_path: str,
        actions: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """
        Execute a sequence of Inkscape actions using --batch-process.

        Args:
            input_path: Input file path
            actions: List of action IDs to execute
            output_path: Optional output path
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        return await self._execute_actions(input_path, actions, output_path, timeout)

    async def get_document_info(self, input_path: str, timeout: int | None = None) -> str:
        """
        Get document information and metadata from SVG file.

        Args:
            input_path: Input SVG file path
            timeout: Operation timeout in seconds

        Returns:
            str: Document information output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = timeout or self.config.process_timeout

        cmd_args = [
            *self._base_cmd(),
            "--query-all",
            input_path,
        ]

        return await self._execute_command(cmd_args, timeout)

    async def _execute_command(self, cmd_args: list[str], timeout: int) -> str:
        """
        Execute command with proper error handling and logging.
        """
        stdout, _ = await self._execute_command_capture(cmd_args, timeout)
        return stdout

    async def _execute_command_capture(self, cmd_args: list[str], timeout: int) -> tuple[str, str]:
        """Run Inkscape and return ``(stdout, stderr)``.

        Callers that need to inspect stderr — action-argument errors, missing-id
        warnings — use this; `_execute_command` keeps returning stdout alone so
        the `float()` parsers downstream stay unpoisoned by Gtk chatter.
        """
        try:
            # Use asyncio.create_subprocess_exec for better async handling
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._get_environment(),
            )

            try:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout)

                # Return only stdout. Inkscape writes parseable output (dimensions,
                # --query-* results) to stdout and Gtk theme warnings to stderr;
                # concatenating them poisons every float() parser downstream.
                output = stdout_b.decode("utf-8", errors="replace")
                stderr_text = stderr_b.decode("utf-8", errors="replace")

                if process.returncode != 0:
                    error_msg = (
                        f"Inkscape command failed with return code {process.returncode}: {stderr_text or output}"
                    )
                    raise InkscapeExecutionError(error_msg)

                return output, stderr_text

            except TimeoutError as e:
                process.kill()
                await process.wait()
                raise InkscapeTimeoutError(f"Command timed out after {timeout} seconds") from e

        except FileNotFoundError as e:
            raise InkscapeExecutionError(f"Inkscape executable not found: {self.config.inkscape_executable}") from e
        except Exception as e:
            raise InkscapeExecutionError(f"Command execution failed: {e}") from e

    def _get_environment(self) -> dict[str, str]:
        """
        Get environment variables for subprocess execution.
        """
        env = os.environ.copy()

        # Ensure UTF-8 encoding
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"

        return env
