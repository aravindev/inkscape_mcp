"""
FastMCP 3.2 Prefab UI definitions for inkscape_mcp.

GenerativeUI provider: prefab-ui >= 0.14.0
Renders directly in Claude Desktop / supporting clients.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prefabs(mcp: FastMCP) -> bool:
    """Register Prefab UI components with the FastMCP instance.

    Returns True if components were registered, False if prefab-ui is unavailable — the
    caller needs the distinction so it doesn't log a successful registration that never
    happened.
    """

    try:
        from fastmcp.prefab import Button, Column, Dropdown, Text, prefab
    except ImportError:
        import logging

        logging.getLogger(__name__).warning(
            "prefab-ui not installed — Prefab UI unavailable. Run: uv add 'prefab-ui>=0.14.0'"
        )
        return False

    @prefab(mcp, tool="inkscape_system")
    def inkscape_system_prefab() -> Any:
        """Quick status panel for inkscape_system."""
        return Column(
            children=[
                Text(value="Inkscape system", style={"fontWeight": "500", "fontSize": "14px"}),
                Dropdown(
                    param="operation",
                    label="Operation",
                    options=[
                        "status",
                        "version",
                        "diagnostics",
                        "help",
                        "config",
                        "list_extensions",
                        "execute_extension",
                    ],
                    default="status",
                ),
                Button(label="Run", action="submit"),
            ]
        )

    return True
