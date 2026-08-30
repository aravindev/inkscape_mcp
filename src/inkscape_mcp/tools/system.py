"""System operations and diagnostics for Inkscape MCP server.

PORTMANTEAU PATTERN RATIONALE:
Consolidates 7 system management operations into single interface. Prevents tool explosion
while maintaining
clean separation of concerns. Follows FastMCP 2.14.1+ SOTA standards.

SUPPORTED OPERATIONS:
- status: Get comprehensive server and Inkscape status
- help: Get help information and tool descriptions
- diagnostics: Run diagnostic checks and system readiness
- version: Get server version and protocol information
- config: View current configuration settings
- list_extensions: Discover and list available Inkscape extensions
- execute_extension: Execute Inkscape extensions with parameters

OPERATIONS DETAIL:

**Status & Health**:
  - status: Get comprehensive server and Inkscape status, tool availability, and system health

**Version Information**:
  - version: Get server version, protocol version, architecture, and Inkscape requirements

**Diagnostics**:
  - diagnostics: Run diagnostic checks to verify configuration, dependencies, and system readiness

**Help & Documentation**:
  - help: Get comprehensive help information including tool descriptions and getting started guide

**Extension Management**:
  - list_extensions: Discover and list all available Inkscape extensions with metadata
  - execute_extension: Execute Inkscape extensions with parameters and file I/O

**Configuration**:
  - config: View current configuration including Inkscape executable path, timeouts, and settings

Args:
    operation (Literal, required): The system operation to perform. Must be one of:
        "status", "help", "diagnostics",
        "version", "config", "list_extensions", "execute_extension".
        - "status": Get server and Inkscape status (no additional parameters)
        - "help": Get help information and tool descriptions (no additional parameters)
        - "diagnostics": Run diagnostic checks (no additional parameters)
        - "version": Get version information (no additional parameters)
        - "config": View current configuration (no additional parameters)
        - "list_extensions": List available Inkscape extensions (no additional parameters)
        - "execute_extension": Execute Inkscape extension (requires: extension_id, additional
        parameters)

    extension_id (str | None): Identifier for Inkscape extension. Required for:
        execute_extension operation.

    cli_wrapper (Any): Injected CLI wrapper dependency. Required. Handles Inkscape command
        execution.

    config (Any): Injected configuration dependency. Required. Contains Inkscape executable path
        and settings.

Returns:
    FastMCP 2.14.1+ Enhanced Response Pattern with success/error states, execution timing,
    next steps, and recovery options for failed operations.

Examples:
    # Get server status
    result = await inkscape_system(
        operation="status"
    )

    # Get help information
    result = await inkscape_system(
        operation="help"
    )

    # Run diagnostics
    result = await inkscape_system(
        operation="diagnostics"
    )

    Success Response (status operation):
    {
      "success": true,
      "operation": "status",
      "summary": "System status retrieved successfully",
      "result": {
        "data": {
          "server": {
            "name": "Inkscape MCP Server",
            "version": "1.1.0",
            "status": "running"
          },
          "inkscape": {
            "available": true,
            "version": "Inkscape 1.2.1",
            "executable": "/usr/bin/inkscape"
          },
          "tools": {
            "file": "available",
            "vector": "available",
            "analysis": "available",
            "system": "available"
          }
        },
        "execution_time_ms": 45.67
      },
      "next_steps": ["Use inkscape_file for basic operations",
        "Run diagnostics if issues detected"],
      "context": {
        "operation_details": "All systems operational"
      },
      "suggestions": ["Verify Inkscape version meets requirements",
        "Check configuration if tools unavailable"],
      "follow_up_questions": ["Need help getting started?", "Experiencing any issues?"]
    }

    Success Response (help operation):
    {
      "success": true,
      "operation": "help",
      "summary": "Help information retrieved",
      "result": {
        "data": {
          "server": "Inkscape MCP Server",
          "description": "Professional vector graphics and SVG editing through Model Context
            Protocol",
          "tools": [
            "inkscape_file: Basic file operations",
            "inkscape_vector: Advanced vector operations",
            "inkscape_analysis: Document analysis",
            "inkscape_system: System operations"
          ],
          "getting_started": [
            "Ensure Inkscape 1.0+ is installed",
            "Use inkscape_file for basic operations",
            "Use inkscape_vector for advanced vector editing"
          ]
        },
        "execution_time_ms": 12.34
      },
      "next_steps": ["Try inkscape_file load operation", "Explore inkscape_vector operations"],
      "context": {
        "operation_details": "Complete tool reference available"
      },
      "suggestions": ["Start with file operations", "Progress to vector operations"],
      "follow_up_questions": ["Which operation would you like to try first?",
        "Need examples for specific operations?"]
    }

    Error Response (Error Recovery Pattern):
    {
      "success": false,
      "operation": "operation_name",
      "error": "Error type (e.g., ValueError)",
      "message": "Human-readable error description",
      "recovery_options": ["Verify operation name is correct", "Check configuration is loaded",
        "Ensure Inkscape is installed"],
      "diagnostic_info": {
        "config_loaded": false,
        "inkscape_available": false,
        "operation_valid": true
      },
      "alternative_solutions": ["Run diagnostics operation", "Check server logs",
        "Verify installation"]
    }

Examples:
    # Get comprehensive system status
    result = await inkscape_system(
        operation="status"
    )

    # Get version information
    result = await inkscape_system(
        operation="version"
    )

    # Run diagnostic checks
    result = await inkscape_system(
        operation="diagnostics"
    )

    # Get help information
    result = await inkscape_system(
        operation="help"
    )

    # View current configuration
    result = await inkscape_system(
        operation="config"
    )

Errors:
    - ValueError: Invalid operation or parameter values
        Recovery options:
        - Verify operation is one of: status, help, diagnostics, version, config
        - Check operation name spelling and case sensitivity
        - Ensure no additional parameters are provided for system operations

    - FileNotFoundError: Configuration file not found
        Recovery options:
        - Verify configuration file exists in expected location
        - Check file permissions (read access required)
        - Ensure configuration is properly initialized
        - Run diagnostics to identify configuration issues

    - PermissionError: Insufficient permissions for system operations
        Recovery options:
        - Check user permissions for reading configuration
        - Verify file system permissions
        - Run with appropriate user privileges
        - Check antivirus or security software blocking access

    - ConnectionError: Cannot connect to Inkscape or system services
        Recovery options:
        - Verify Inkscape installation (run inkscape --version manually)
        - Check Inkscape executable path in configuration
        - Ensure Inkscape is accessible from command line
        - Run diagnostics operation to identify connection issues
"""

import asyncio
import time
from typing import Any

from pydantic import BaseModel

from ..mcp_tool_types import InkscapeSystemOperation


def _server_version() -> str:
    """Real package version — these used to be hardcoded and drifted three releases behind."""
    from .. import __version__

    return __version__


def _fastmcp_version() -> str:
    try:
        from fastmcp import __version__ as v

        return str(v)
    except Exception:
        return "unknown"


class SystemResult(BaseModel):
    """Result model for system operations."""

    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


async def inkscape_system(
    operation: InkscapeSystemOperation,
    extension_id: str | None = None,
    extension_params: dict[str, Any] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
    cli_wrapper: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """Inkscape system operations portmanteau tool."""
    start_time = time.time()

    try:
        if operation == "status":
            # Get server and Inkscape status
            inkscape_available = False
            inkscape_version = "unknown"

            try:
                if config and config.inkscape_executable:
                    result = await cli_wrapper._execute_command(
                        [str(config.inkscape_executable), "--app-id-tag=mcp", "--version"],
                        config.process_timeout,
                    )
                    inkscape_available = True
                    inkscape_version = result.strip().split("\n")[0] if result else "unknown"
            except Exception:  # noqa: S110 — diagnostics call; missing Inkscape simply leaves the flags False
                pass

            return SystemResult(
                success=True,
                operation="status",
                message="Retrieved system status",
                data={
                    "server": {
                        "name": "Inkscape MCP Server",
                        "version": _server_version(),
                        "status": "running",
                    },
                    "inkscape": {
                        "available": inkscape_available,
                        "version": inkscape_version,
                        "executable": str(config.inkscape_executable) if config else None,
                    },
                    "tools": {
                        "file": "available",
                        "vector": "available",
                        "analysis": "available",
                        "system": "available",
                    },
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "version":
            # Get version information
            return SystemResult(
                success=True,
                operation="version",
                message="Retrieved version information",
                data={
                    "server": f"Inkscape MCP Server v{_server_version()}",
                    "protocol": f"FastMCP {_fastmcp_version()}",
                    "architecture": "Portmanteau Tools",
                    "inkscape_required": "1.4.x (Actions API; older lines are unsupported)",
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "diagnostics":
            # Run basic diagnostic checks
            checks = {
                "config_loaded": config is not None,
                "cli_wrapper_available": cli_wrapper is not None,
                "inkscape_executable_set": bool(config and config.inkscape_executable) if config else False,
            }

            try:
                from ..dbus_client import InkscapeDBus
                from ..extension_bridge import bridge_status, needs_inkscape_restart

                bridge = bridge_status()

                # jeepney's send_and_get_reply blocks with no timeout, so probing the bus
                # inline can wedge the whole event loop on a stalled Inkscape. Run the probe
                # in a worker thread and give up after a beat.
                def _probe() -> dict[str, Any]:
                    bus = InkscapeDBus()
                    if bus.is_available():
                        return {"live": True, "needs_restart": needs_inkscape_restart(bus)}
                    return {"live": False}

                try:
                    bridge.update(await asyncio.wait_for(asyncio.to_thread(_probe), timeout=5.0))
                except TimeoutError:
                    bridge["live"] = False
                    bridge["probe"] = "timed out after 5s"
            except Exception as exc:
                bridge = {"error": str(exc)}

            return SystemResult(
                success=True,
                operation="diagnostics",
                message="Ran diagnostic checks",
                data={
                    "checks": checks,
                    "all_passed": all(checks.values()),
                    "issues": [k for k, v in checks.items() if not v],
                    "bridge": bridge,
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "list_extensions":
            # Previously a stub claiming "Extension system disabled - plugins directory
            # removed", which contradicted the fully working inkscape_extension tool.
            from .extension import _op_list

            listed = _op_list("list_extensions", "", start_time)
            extensions = listed.get("data", {}).get("extensions", [])
            return SystemResult(
                success=listed["success"],
                operation="list_extensions",
                message=listed["message"],
                data={
                    "extensions": extensions,
                    "total_count": len(extensions),
                    "categories": sorted({e.get("category", "") for e in extensions if e.get("category")}),
                },
                execution_time_ms=(time.time() - start_time) * 1000,
                error=listed.get("error", ""),
            ).model_dump()

        elif operation == "execute_extension":
            if not extension_id:
                return SystemResult(
                    success=False,
                    operation="execute_extension",
                    message="Extension ID is required",
                    data={},  # required field; omitting it raised a ValidationError that
                    # masked this message entirely
                    error="Missing extension_id parameter",
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()
            if not input_file:
                return SystemResult(
                    success=False,
                    operation="execute_extension",
                    message="input_file is required to execute an extension",
                    data={"extension_id": extension_id},
                    error="Missing input_file parameter",
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            from .extension import _op_run

            ran = await _op_run(
                "execute_extension",
                extension_id,
                extension_params or {},
                input_file,
                output_file or "",
                start_time,
            )
            return SystemResult(
                success=ran["success"],
                operation="execute_extension",
                message=ran["message"],
                data=ran.get("data", {}),
                execution_time_ms=(time.time() - start_time) * 1000,
                error=ran.get("error", ""),
            ).model_dump()

        elif operation == "help":
            # Provide help information
            help_info = {
                "server": "Inkscape MCP Server",
                "description": "Professional vector graphics and SVG editing through Model Context Protocol",
                "tools": [
                    "inkscape_file: Basic file operations (load, save, convert, info, validate, list_formats)",
                    "inkscape_vector: Advanced vector ops (23 operations: trace, boolean, optimize, render, ...)",
                    "inkscape_analysis: Document analysis (quality, statistics, validate, objects, dimensions)",
                    "inkscape_system: System operations (status, help, diagnostics, version, config)",
                ],
                "getting_started": [
                    "Ensure Inkscape 1.0+ is installed",
                    "Use inkscape_file for basic operations",
                    "Use inkscape_vector for advanced vector editing",
                    "Use inkscape_analysis to understand your SVGs",
                ],
            }

            return SystemResult(
                success=True,
                operation="help",
                message="Retrieved help information",
                data=help_info,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "config":
            # View configuration
            config_data = {}
            if config:
                config_data = {
                    "inkscape_executable": str(config.inkscape_executable) if config.inkscape_executable else None,
                    "process_timeout": config.process_timeout if hasattr(config, "process_timeout") else None,
                    "max_concurrent_processes": config.max_concurrent_processes
                    if hasattr(config, "max_concurrent_processes")
                    else None,
                }

            return SystemResult(
                success=True,
                operation="config",
                message="Retrieved configuration",
                data=config_data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        else:
            # Defensive: unreachable for a well-typed caller, but the tools are also
            # invoked directly (tests, other tools) where `operation` is just a str.
            return SystemResult(  # type: ignore[unreachable]
                success=False,
                operation=operation,
                message=f"Unknown operation: {operation}",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="ValueError",
            ).model_dump()

    except Exception as e:
        return SystemResult(
            success=False,
            operation=operation,
            message=f"System operation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        ).model_dump()
