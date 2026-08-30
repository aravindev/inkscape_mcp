# API Reference

Eight portmanteau tools, each taking an `operation` string plus per-operation
parameters. Operation strings are typed via Python `Literal[...]` in
`src/inkscape_mcp/mcp_tool_types.py` — clients see them as a closed enum in
each tool's JSON schema.

Every tool returns a dict containing at minimum:

```python
{
    "success": bool,
    "operation": str,
    "message": str,  # short human-readable summary
    "data": dict | list | None,  # operation-specific result payload
    "execution_time_ms": float,
    "error": str,  # only set when success=False
}
```

Paths must be absolute or be readable under one of `allowed_directories` in
the server config.

---

## inkscape_file

Load, convert, export, and validate SVG and other vector files via the
Inkscape CLI.

| Operation | Required params | Purpose |
|-----------|-----------------|---------|
| `load` | `input_path` | Read/validate that a path exists for an editing workflow. |
| `save` | `input_path`, `output_path` | Persist changes. |
| `convert` | `input_path`, `output_path`, `format` | Export to pdf, png, eps, ps, … via `--export-type`. |
| `info` | `input_path` | Filesystem metadata + dimensions. |
| `validate` | `input_path` | Structural check via CLI query. |
| `list_formats` | — | Bounded list of supported export formats. |
| `batch_convert` | `input_path`, `output_path`, `format` | Convert all files in a directory. |

## inkscape_vector

Vector editing, booleans, tracing, path manipulation, optimization, layout,
LPE, and barcode/QR generation. 47 operations — full list in
`InkscapeVectorOperation` (`mcp_tool_types.py`). Highlights:

- **Tracing & generation:** `trace_image`, `generate_barcode_qr`, `generate_laser_dot`, `create_mesh_gradient`, `construct_svg`.
- **Boolean ops:** `apply_boolean` (union / difference / intersect / exclude / division / cut).
- **Path ops:** `path_simplify`, `path_clean`, `path_combine`, `path_break_apart`, `object_to_path`, `stroke_to_path`, `path_inset_outset`, `path_split`, `path_fill_between`.
- **Optimization:** `optimize_svg`, `scour_svg`.
- **Geometry & layout:** `measure_object`, `query_document`, `count_nodes`, `fit_canvas_to_drawing`, `set_document_units`, `align`, `distribute`, `flip_horizontal`, `flip_vertical`, `rotate_90_cw`, `rotate_90_ccw`, `object_raise`, `object_lower`, `page_fit_to_selection`, `page_rotate`.
- **Cloning & grouping:** `ungroup`, `clone`, `clone_unlink`, `object_to_marker`, `object_to_pattern`, `tile_clone`.
- **Text:** `text_to_path`, `text_on_path`.
- **LPE (Live Path Effects):** `lpe_add_corners`, `lpe_remove`, `lpe_paste`, `lpe_clone_link`.
- **Export:** `render_preview`, `export_dxf`, `layers_to_files`.

Common signature: `inkscape_vector(operation, input_path, output_path="")`.

## inkscape_analysis

Read-only inspection.

| Operation | Returns |
|-----------|---------|
| `quality` | Complexity score + optimization hints. |
| `statistics` | File size, dimensions, object count, layers. |
| `validate` | `{valid, errors[], warnings[]}`. |
| `objects` | Bounded list of `{id, type, x, y, w, h}`. |
| `dimensions` | Width, height, aspect ratio. |
| `structure` | Layer hierarchy + groups. |

Signature: `inkscape_analysis(operation, input_path)`.

## inkscape_system

Server-side operations and Inkscape diagnostics.

| Operation | Returns |
|-----------|---------|
| `status` | Server state, Inkscape version, tool availability. |
| `version` | Server version, FastMCP version, Inkscape requirements. |
| `diagnostics` | Config provenance, Inkscape reachability, D-Bus bridge state, extension-bridge restart flag. |
| `help` | Tool descriptions and getting-started text. |
| `config` | Effective config values. |
| `list_extensions` | Available Inkscape extensions on disk. |
| `execute_extension` | Run a named extension via CLI. |

Signature: `inkscape_system(operation)`.

## inkscape_extension

Discover and invoke any installed inkex extension.

| Operation | Required params | Purpose |
|-----------|-----------------|---------|
| `list` | — (optional `target` substring filter) | Catalog of installed extensions. |
| `describe` | `target` (extension id) | Full parameter schema. |
| `run` | `target`, `params` (JSON), `input_path`, optional `output_path` | Headless invocation. |
| `run_live` | `target`, `params`, optional `wrapper_id` | Invoke on the running Inkscape document. With `wrapper_id` set, any prior element with that id is removed first so CSS / style hooks keep targeting it. |

## inkscape_gradient

Manipulate `<linearGradient>` / `<radialGradient>` definitions in the SVG.

| Operation | Required params | Purpose |
|-----------|-----------------|---------|
| `add_stop` | `gradient_id`, `stop_offset`, `stop_color`, `stop_opacity` | Add a stop. |
| `remove_stop` | `gradient_id`, `stop_offset` | Remove the stop at an offset. |
| `set_stop_color` | `gradient_id`, `stop_offset`, `stop_color`, `stop_opacity` | Recolor a stop. |
| `convert_to_linear` | `gradient_id` | Convert radial → linear. |
| `convert_to_radial` | `gradient_id` | Convert linear → radial. |
| `list_stops` | `gradient_id` | Return the stops on a gradient. |

Signature: `inkscape_gradient(operation, input_path, output_path, gradient_id="", stop_offset="", stop_color="", stop_opacity=1.0)`.

## inkscape_metadata

Read and write Dublin-Core metadata in the SVG's `<rdf:RDF>` block.

| Operation | Required params |
|-----------|-----------------|
| `get` | `input_path` |
| `set_title` | `input_path`, `output_path`, `value` |
| `set_creator` | `input_path`, `output_path`, `value` |
| `set_description` | `input_path`, `output_path`, `value` |
| `set_rights` | `input_path`, `output_path`, `value` |
| `set_keywords` | `input_path`, `output_path`, `value` |

## inkscape_live

Drive a running Inkscape window via D-Bus + clipboard staging. Edits appear
on the canvas in real time and are individually undoable.

| Operation | Purpose |
|-----------|---------|
| `ping` | Confirm the D-Bus bridge is reachable. |
| `apply_action` | Run any `inkscape --action` verb on the live document. |
| `list_actions` | Filtered list of D-Bus-reachable actions (use `target` substring). |
| `get_document_xml` | Snapshot the live SVG. |
| `get_selection` | Read the current selection. |
| `set_selection` | Select objects by id. |
| `insert_svg` | Paste an SVG fragment at the cursor (via clipboard). |
| `delete_selected` | Delete the active selection. |
| `open_file` | Open a file in the running window. |
| `save_snapshot` | Save the current state to disk. |
| `edit_xml` | Set/delete an attribute on an element by id. |
| `path_edit` | Mutate `d` data on a path. |
| `inspect_selection` / `inspect_layers` / `inspect_defs` / `inspect_view` / `inspect_pages` / `inspect_element` | Bounded read-only inspectors. |
| `execute_inkex` | Run an installed inkex extension on the live document. |
| `rasterize` | Render the doc / an element / an area to PNG so the agent can see the result. |

Signature: `inkscape_live(operation, target="", payload="", window_id=1)`.

`payload` is a JSON string when the operation needs structured arguments
(e.g. `rasterize` takes `{"area": "x:y:w:h", "dpi": 192, "filename": "..."}`).
Full payload shapes are in `src/inkscape_mcp/reference/mcp-workflow.md`.

---

## Errors

Failure payloads keep the same envelope, with `success=False`:

```python
{
    "success": False,
    "operation": "...",
    "message": "Human-readable description",
    "error": "ErrorType or short error string",
    "execution_time_ms": 12.3,
    "data": {...},  # optional diagnostic info
}
```

## Access control

No authentication. Access is gated by:

- `allowed_directories` in the server config.
- Filesystem permissions of the user running the server.
- A per-process timeout (`process_timeout`) on every Inkscape invocation.

## Discovery resources

The server also exposes the captured Inkscape 1.4.4 reference as MCP resources
so agents can learn the underlying surface without shelling out:

- `resource://inkscape/cli-actions` — full `inkscape --action-list`.
- `resource://inkscape/cli-help` — full `inkscape --help`.
- `resource://inkscape/mcp-workflow` — operational guide with recipes and gotchas.
- `resource://inkscape/capabilities` — capability summary.
- `resource://inkscape/skills` — LLM-oriented skill notes.
