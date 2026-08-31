# inkscape_mcp skills

Eight portmanteau tools. Each takes an `operation` string plus per-op
parameters. Operation enums are typed `Literal[...]` so wrong strings fail at
parse time.

## How to work with this server

**Compose; don't hand-write a finished SVG.** Place primitives, then let Inkscape
derive the geometry — `align` / `distribute` for layout, `apply_boolean` to cut and
merge, `clone` / `tile_clone` for repetition, `run_live` (no params) for filters and
effects. Give everything a stable `id` as you create it, because ids are the handle
for every later edit.

**Look at what you made.** `inkscape_live(operation="rasterize")` renders the doc, an
element, or a region to PNG — read it back and judge the result instead of assuming.

**Collaborate.** When the target is ambiguous, ask the user to select it on canvas and
read it with `get_selection`. When they ask where a setting is, open the dialog for
them with `apply_action("dialog-open", payload=...)`.

Full operational guide, gotchas, and Inkscape rendering pitfalls:
`resource://inkscape/mcp-workflow`.

## inkscape_file

Load, convert, export, validate SVG and other vector files via the Inkscape CLI.

**Operations:** `load` | `save` | `convert` | `info` | `validate` | `list_formats` | `batch_convert`

**Common pattern:**

1. `inkscape_file(operation="validate", input_path="...")` — check before editing
2. `inkscape_file(operation="convert", input_path="...", output_path="...", format="pdf")` — export

---

## inkscape_vector

Vector editing, booleans, tracing, path manipulation, optimization, layout, LPE, barcode/QR. 49 ops total.

**Highlights:** `trace_image` | `generate_barcode_qr` | `apply_boolean` | `path_simplify` | `optimize_svg` | `scour_svg` | `render_preview` | `export_dxf` | `layers_to_files` | `text_to_path` | `align` | `distribute` | `lpe_add_corners` | `tile_clone`

**Ops that need an argument** (they error rather than no-op if you omit it):
`align` and `distribute` need `operation_type` — `align` takes `left`/`hcenter`/`right`
and/or `top`/`vcenter`/`bottom` plus an optional anchor (`"top"`, `"hcenter vcenter"`,
`"top page"`); `distribute` takes exactly one of `hgap`/`left`/`hcenter`/`right`/`vgap`/
`top`/`vcenter`/`bottom`. `apply_boolean` needs `union`/`difference`/`intersection`/
`exclusion`. `measure_object` needs `object_id` (use `query_document` for the whole drawing).

**`optimize_svg` vs `scour_svg`:** both run Inkscape's plain-SVG export, which strips the
`inkscape:` namespace and so demotes layers to plain groups (reported as `layers_demoted`).
`scour_svg` adds a real scour minification pass — use it when you want the file smaller,
since plain-SVG export alone pretty-prints and often grows it.

Source of truth: `InkscapeVectorOperation` in `mcp_tool_types.py`.

---

## inkscape_analysis

Read-only inspection of SVG structure, quality, dimensions. Always call before mutating.

**Operations:** `quality` | `statistics` | `validate` | `objects` | `dimensions` | `structure`

---

## inkscape_system

Server/Inkscape status, help, diagnostics, version, extension discovery.

**Operations:** `status` | `help` | `diagnostics` | `version` | `config` | `list_extensions` | `execute_extension`

First step for any failure: `inkscape_system(operation="diagnostics")` — reports Inkscape reachability, config provenance, and D-Bus bridge state.

---

## inkscape_extension

Discover and invoke any installed inkex extension.

**Operations:** `list` (with optional `target` substring filter) | `describe` (full param schema for one extension) | `run` (headless on a file) | `run_live` (on the running Inkscape document; pass `wrapper_id` to re-render in place)

---

## inkscape_gradient

Add/remove/recolor gradient stops, convert linear↔radial.

**Operations:** `add_stop` | `remove_stop` | `set_stop_color` | `convert_to_linear` | `convert_to_radial` | `list_stops`

---

## inkscape_metadata

Read and write Dublin-Core RDF metadata in the SVG's `<rdf:RDF>` block.

**Operations:** `get` | `set_title` | `set_creator` | `set_description` | `set_rights` | `set_keywords`

---

## inkscape_live

Drive a running Inkscape window via D-Bus + clipboard staging. Every edit is a normal undo entry.

**Highlights:** `apply_action` (any of ~1,070 Inkscape verbs) | `list_actions` (filtered) | `get_selection` | `set_selection` | `insert_svg` | `edit_xml` | `path_edit` | `inspect_selection` / `inspect_layers` / `inspect_defs` / `inspect_view` / `inspect_pages` / `inspect_element` | `execute_inkex` | `rasterize` (render doc/element/area to PNG so the agent can see the canvas)

`payload` is a JSON string when an op needs structured arguments. Full payload shapes in `inkscape_mcp/reference/mcp-workflow.md` (also exposed as `resource://inkscape/mcp-workflow`).

---

## Environment

- Tested with Inkscape 1.4.4 on Ubuntu 24.04.
- Transport: `MCP_TRANSPORT=stdio` (default) or `MCP_TRANSPORT=http` for MCP-streamable HTTP on `/mcp`.
- Inkscape binary resolved via `INKSCAPE_BIN`, then PATH, then well-known install locations.
- CLI tools degrade gracefully (with a warning) when Inkscape isn't found; live D-Bus ops require a running Inkscape window.
- This skill file is exposed at runtime as `resource://inkscape/skills`.
