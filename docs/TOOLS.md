# Available tools

The server exposes eight portmanteau tools. Each takes an `operation` string
that picks the actual behavior — keeps the surface scannable for the agent.

> **For the operational guide** — picking the right op, gotchas, recipes for
> retired tools, Inkscape rendering pitfalls — see
> [`src/inkscape_mcp/reference/mcp-workflow.md`](../src/inkscape_mcp/reference/mcp-workflow.md).
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

49 operations. The full list is enumerated in
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

### Operations with required or notable arguments

| Operation | Argument | Notes |
|-----------|----------|-------|
| `align` | `operation_type` **required** | One or two of `left`/`hcenter`/`right` and `top`/`vcenter`/`bottom`, plus an optional anchor (`last`, `first`, `biggest`, `smallest`, `page`, `drawing`, `selection`, `pref`). E.g. `"top"`, `"hcenter vcenter"`, `"top page"`. `object_ids` scopes the selection; omit it to align everything. |
| `distribute` | `operation_type` **required** | Exactly one of `hgap`, `left`, `hcenter`, `right`, `vgap`, `top`, `vcenter`, `bottom`. |
| `apply_boolean` | `operation_type` **required** | `union`, `difference`, `intersection` or `exclusion`. Supply `object_ids` or `select_all`. |
| `trace_image` | `trace_scans` (4), `trace_smooth` (true), `trace_stack` (true), `trace_remove_background` (false), `trace_speckles` (2), `trace_smooth_corners` (1.0), `trace_optimize` (0.2) | Defaults give a 4-scan stacked colour trace. Raise `trace_scans` for more colour detail, `trace_speckles` to drop more noise. Fails rather than succeeding empty if the trace yields no paths. |
| `measure_object` | `object_id` **required** | Returns that object's bbox. Use `query_document` for whole-drawing dimensions; a missing id is an error, not a silent fallback. |
| `optimize_svg` | — | Inkscape plain-SVG export plus an unused-`<defs>` sweep. Being plain SVG, it strips the `inkscape:` namespace and so **demotes layers to plain groups** — the result reports `layers_demoted`. |
| `scour_svg` | — | Everything `optimize_svg` does, then a real [scour](https://github.com/scour-project/scour) minification pass. Use this when you want the file to get *smaller*; plain-SVG export alone pretty-prints and often grows it. Ids are preserved so other ops can still address elements. |

Inkscape actions that take an argument (`object-align`, `object-distribute`,
`object-trace`) are rejected by Inkscape when fired bare — it logs the failure to
stderr and still exits 0. `InkscapeCliWrapper._execute_actions` scans stderr for
those messages and raises, so a rejected action can no longer be reported as success.

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
| `diagnostics` | `config_sources` provenance (CLI flag / env var / config file / auto-detected / default), Inkscape reachability, D-Bus bridge state, extension-bridge restart flag. |
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
| `run_live` | `target`, `params`, optional `wrapper_id` | Invoke against the running Inkscape. **The two param modes are not interchangeable — see below.** `wrapper_id` re-renders in place. |

### `run_live`: pick the mode that matches the extension

| | No `params` | With `params` |
|---|---|---|
| Mechanism | Fires `<id>.noprefs` over D-Bus | Renders headlessly on an **empty canvas**, appends the output in a `<g id="mcp-ext-…">` |
| Sees the open document? | Yes | **No** |
| Sees the selection? | Yes | **No** |
| Undo | One native Inkscape undo entry | One `MCP: Edit` entry |
| Use for | **Transformer** extensions — filters, drop shadow, blur, colour shift, path effects | **Generator** extensions — QR, barcode, calendar, gears, polyhedra, pdflatex |

For a transformer, select the target first with `inkscape_live(operation="set_selection")`, then call
`run_live` with no params. Running a transformer *with* params hands it a blank canvas, so it
produces nothing or fails with "select at least one element"; pass no params, or use `run` against a
file instead.

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
[`src/inkscape_mcp/reference/mcp-workflow.md`](../src/inkscape_mcp/reference/mcp-workflow.md).

## How an agent discovers the right usage

Three surfaces, differing in whether the agent gets them for free:

| Surface | Delivery | Contents |
|---|---|---|
| **Server instructions** | **Pushed** — returned in `InitializeResult.instructions`, which MCP clients may add to the system prompt | The working method: compose procedurally rather than hand-writing SVG, rasterize and look at the result, ask the user to select ambiguous targets, open dialogs on request. Plus the live/headless mechanics. Defined as `SERVER_INSTRUCTIONS` in `main.py`. |
| **Tool descriptions** | **Pushed** — sent with the tool list | Per-operation semantics, required arguments, the `run_live` mode split. |
| **Prompts and resources** | **Pull** — the agent (or user) must request them | The deep material below. The server instructions name `mcp-workflow` explicitly so an agent knows to fetch it. |

Registered MCP prompts (surfaced by many clients as slash commands):

- `prompt://inkscape/design-workflow` — **the default design loop**: block out primitives,
  let Inkscape derive geometry, apply effects, rasterize and iterate.
- `prompt://inkscape/svg-file-workflow`
- `prompt://inkscape/vector-editing-workflow`
- `prompt://inkscape/analysis-workflow`

Registered resources:

- `resource://inkscape/capabilities` — capability summary.
- `resource://inkscape/skills` — LLM-oriented skill notes from `skills/SKILL.md`.
- `resource://inkscape/mcp-workflow` — operational guide with recipes and gotchas.
  **Read this one first for anything non-trivial** — it carries the procedural-composition
  loop, the collaboration patterns, and the Inkscape rendering pitfalls (silently broken
  `feDropShadow`, filter-bound clamping) that otherwise ruin output with no error.
- `resource://inkscape/cli-actions` — full `inkscape --action-list` capture.
- `resource://inkscape/cli-help` — full `inkscape --help` capture.
