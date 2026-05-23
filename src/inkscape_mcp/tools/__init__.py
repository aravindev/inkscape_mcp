"""Inkscape MCP portmanteau tool surface.

Each tool takes an ``operation`` string that selects the underlying Inkscape CLI
or D-Bus behavior, keeping the agent-facing surface compact and discoverable.

- inkscape_file       — load / save / convert / info / validate / list_formats
- inkscape_vector     — boolean / path / trace / optimize / render / barcode / ...
- inkscape_analysis   — quality / statistics / validate / objects / dimensions / structure
- inkscape_system     — status / help / diagnostics / version / config / extensions
- inkscape_extension  — discover and invoke installed inkex extensions
- inkscape_gradient   — gradient stop manipulation
- inkscape_metadata   — Dublin-Core RDF metadata
- inkscape_live       — drive the running Inkscape GUI via D-Bus
"""

from .analysis import inkscape_analysis
from .extension import inkscape_extension
from .file_operations import inkscape_file
from .gradient import inkscape_gradient
from .live import inkscape_live
from .metadata import inkscape_metadata
from .system import inkscape_system
from .vector_operations import inkscape_vector

__all__ = [
    "inkscape_analysis",
    "inkscape_extension",
    "inkscape_file",
    "inkscape_gradient",
    "inkscape_live",
    "inkscape_metadata",
    "inkscape_system",
    "inkscape_vector",
]
