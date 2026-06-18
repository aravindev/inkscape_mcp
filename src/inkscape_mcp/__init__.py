"""Inkscape MCP Server — drive Inkscape from an AI agent.

FastMCP 3.2+ server exposing 8 portmanteau tools that shell out to the
Inkscape CLI or drive a running Inkscape window via D-Bus:

- inkscape_file       — load, save, convert, info, validate
- inkscape_vector     — vector ops (boolean, path, trace, optimize, ...)
- inkscape_analysis   — read-only inspection (quality, statistics, structure)
- inkscape_system     — server / Inkscape status, diagnostics, version
- inkscape_extension  — discover and invoke installed inkex extensions
- inkscape_gradient   — gradient stop manipulation
- inkscape_metadata   — Dublin-Core RDF metadata
- inkscape_live       — drive the running Inkscape GUI via D-Bus

Entry point: ``inkscape_mcp.main:main``.
"""

__version__ = "1.0.2"
__author__ = "Aravind EV"
__email__ = "aravindev@live.in"

__all__ = ["__version__"]
