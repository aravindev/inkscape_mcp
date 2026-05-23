# Available tools

The server exposes eight portmanteau tools. Each takes an `operation` string
that picks the actual behavior — keeps the surface scannable for the agent.

> **For the operational guide** — picking the right op, gotchas, recipes for
> retired tools, Inkscape rendering pitfalls — see
> [`docs/reference/mcp-workflow.md`](reference/mcp-workflow.md).
>
> Parameter schemas: [API.md](API.md). Source of truth for operation enums:
> `src/inkscape_mcp/mcp_tool_types.py`.

## inkscape_file

| Operation | Inputs | What it does |
|-----------|--------|--------------|
| `load` | `input_path` | Validate that an SVG opens, return dimensions. |
| `save` | `input_path`, `output_path` | Persist with optional reformatting. |
| `convert` | `input_path`, `output_path`, `format` | Export to PDF/PNG/EPS/PS/etc. via `--export-type`. |
| `info` | `input_path` | Dimensions + filesystem metadata. |
| `validate` | `input_path` | Basic structural check via CLI query. |
| `list_formats` | — | Bounded list of supported export formats. |
| `batch_convert` | `input_path`, `output_path`, `format` | Convert every file in a directory. |

## inkscape_vector

47 operations. The full list is enumerated in
`src/inkscape_mcp/mcp_tool_types.py` (`InkscapeVectorOperation` Literal).
Highlights:

- **Tracing & generation:** `trace_image`, `generate_barcode_qr`, `generate_laser_dot`, `create_mesh_gradient`, `construct_svg`.
- **Boolean ops:** `apply_boolean` (`union` / `difference` / `intersect` / `exclude`), `path_division`, `path_cut`.
- **Path ops:** `path_simplify`, `path_clean`, `path_combine`, `path_break_apart`, `object_to_path`, `stroke_to_path`, `path_inset_outset`, `path_split`, `path_fill_between`.
- **Optimization:** `optimize_svg`, `scour_svg`.
- **Geometry & layout:** `measure_object`, `query_document`, `count_nodes`, `fit_canvas_to_drawing`, `set_document_units`, `align`, `distribute`, `flip_horizontal`, `flip_vertical`, `rotate_90_cw`, `rotate_90_ccw`, `object_raise`, `object_lower`, `page_fit_to_selection`, `page_rotate`.
- **Cloning & grouping:** `ungroup`, `clone`, `clone_unlink`, `object_to_marker`, `object_to_pattern`, `tile_clone`.
- **Text:** `text_to_path`, `text_on_path`.
- **LPE (Live Path Effects):** `lpe_add_corners`, `lpe_remove`, `lpe_paste`, `lpe_clone_link`.
- **Export:** `render_preview`, `export_dxf`, `layers_to_files`.

All operations dispatch through `cli_wrapper.InkscapeCliWrapper`, which is
the only place that spawns the `inkscape` binary.

## inkscape_analysis

| Operation | Inputs | Returns |
|-----------|--------|---------|
| `quality` | `input_path` | Complexity score + optimization hints. |
| `statistics` | `input_path` | File size, dimensions, object count, layers. |
| `validate` | `input_path` | `{valid, errors[], warnings[]}`. |
| `objects` | `input_path` | Trimmed list of `{id, type, x, y, w, h}` per object. |
| `dimensions` | `input_path` | Width, height, aspect ratio. |
| `structure` | `input_path` | Layer hierarchy + groups. |

## inkscape_system

| Operation | Returns |
|-----------|---------|
| `status` | Server state, Inkscape version, tool availability. |
| `help` | Tool descriptions and getting-started text. |
| `diagnostics` | Config provenance (CLI flag / env var / file / default), Inkscape reachability, D-Bus bridge state, extension-bridge restart flag. |
| `version` | Server version, FastMCP version, Inkscape requirements. |
| `config` | Effective config values. |
| `list_extensions` | Available Inkscape extensions on disk. |
| `execute_extension` | Run a named extension via CLI. |

## inkscape_extension

Discover and invoke any installed inkex extension.

| Operation | Inputs | Purpose |
|-----------|--------|---------|
| `list` | optional `target` substring filter | Catalog installed extensions. |
| `describe` | `target` (extension id) | Full parameter schema. |
| `run` | `target`, `params` (JSON), `input_path`, optional `output_path` | Headless invocation. |
| `run_live` | `target`, `params`, optional `wrapper_id` | Invoke on the running Inkscape document; `wrapper_id` re-renders in place. |

## inkscape_gradient

| Operation | Purpose |
|-----------|---------|
| `add_stop` | Insert a new gradient stop. |
| `remove_stop` | Remove the stop at an offset. |
| `set_stop_color` | Recolor a stop. |
| `convert_to_linear` | Convert a `<radialGradient>` to `<linearGradient>`. |
| `convert_to_radial` | Convert a `<linearGradient>` to `<radialGradient>`. |
| `list_stops` | Return the stops on a gradient. |

## inkscape_metadata

Dublin-Core RDF metadata in the SVG's `<rdf:RDF>` block.

| Operation | Purpose |
|-----------|---------|
| `get` | Read all metadata fields. |
| `set_title` / `set_creator` / `set_description` / `set_rights` / `set_keywords` | Write a single field. |

## inkscape_live

Drive a running Inkscape window via D-Bus + clipboard staging. 20
operations. Highlights:

- **Bridge:** `ping`.
- **Selection:** `get_selection`, `set_selection`, `delete_selected`.
- **Document:** `get_document_xml`, `open_file`, `save_snapshot`.
- **Editing:** `apply_action`, `insert_svg`, `edit_xml`, `path_edit`.
- **Inspection:** `inspect_selection`, `inspect_layers`, `inspect_defs`, `inspect_view`, `inspect_pages`, `inspect_element`.
- **Discovery:** `list_actions` (filtered).
- **Extensions on live doc:** `execute_inkex`.
- **Vision:** `rasterize` — render the doc / an element / an area to PNG so
  the agent can see the result.

Full payload shapes for each live op are in
[`docs/reference/mcp-workflow.md`](reference/mcp-workflow.md).

## Prompts and resources

Registered MCP prompts:

- `prompt://inkscape/svg-file-workflow`
- `prompt://inkscape/vector-editing-workflow`
- `prompt://inkscape/analysis-workflow`

Registered resources:

- `resource://inkscape/capabilities` — capability summary.
- `resource://inkscape/skills` — LLM-oriented skill notes from `skills/SKILL.md`.
- `resource://inkscape/mcp-workflow` — operational guide with recipes and gotchas.
- `resource://inkscape/cli-actions` — full `inkscape --action-list` capture.
- `resource://inkscape/cli-help` — full `inkscape --help` capture.
