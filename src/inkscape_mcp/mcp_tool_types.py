"""MCP-exposed Literal aliases for portmanteau `operation` params."""

from __future__ import annotations

from typing import Literal

InkscapeFileOperation = Literal[
    "load",
    "save",
    "convert",
    "info",
    "validate",
    "list_formats",
    "batch_convert",
]

InkscapeVectorOperation = Literal[
    "trace_image",
    "generate_barcode_qr",
    "create_mesh_gradient",
    "text_to_path",
    "construct_svg",
    "apply_boolean",
    "path_inset_outset",
    "path_simplify",
    "path_clean",
    "path_combine",
    "path_break_apart",
    "object_to_path",
    "optimize_svg",
    "scour_svg",
    "measure_object",
    "query_document",
    "count_nodes",
    "export_dxf",
    "layers_to_files",
    "fit_canvas_to_drawing",
    "render_preview",
    "generate_laser_dot",
    "object_raise",
    "object_lower",
    "set_document_units",
    "path_division",
    "path_cut",
    "path_split",
    "path_fill_between",
    "stroke_to_path",
    "flip_horizontal",
    "flip_vertical",
    "rotate_90_cw",
    "rotate_90_ccw",
    "align",
    "distribute",
    "ungroup",
    "clone",
    "clone_unlink",
    "object_to_marker",
    "object_to_pattern",
    "text_on_path",
    "page_fit_to_selection",
    "page_rotate",
    "lpe_add_corners",
    "lpe_remove",
    "lpe_paste",
    "lpe_clone_link",
    "tile_clone",
]

InkscapeAnalysisOperation = Literal[
    "quality",
    "statistics",
    "validate",
    "objects",
    "dimensions",
    "structure",
]

InkscapeSystemOperation = Literal[
    "status",
    "help",
    "diagnostics",
    "version",
    "config",
    "list_extensions",
    "execute_extension",
]

InkscapeGradientOperation = Literal[
    "add_stop",
    "remove_stop",
    "set_stop_color",
    "convert_to_linear",
    "convert_to_radial",
    "list_stops",
]

InkscapeLiveOperation = Literal[
    "ping",
    "get_document_xml",
    "get_selection",
    "set_selection",
    "insert_svg",
    "delete_selected",
    "apply_action",
    "list_actions",
    "open_file",
    "save_snapshot",
    "edit_xml",
    "path_edit",
    "inspect_selection",
    "inspect_layers",
    "inspect_defs",
    "inspect_view",
    "inspect_pages",
    "inspect_element",
    "execute_inkex",
    "rasterize",
]

InkscapeMetadataOperation = Literal[
    "get",
    "set_title",
    "set_creator",
    "set_description",
    "set_rights",
    "set_keywords",
]

InkscapeExtensionOperation = Literal[
    "list",
    "describe",
    "run",
    "run_live",
]
