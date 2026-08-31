# MCP workflow reference

Operational guide for driving `inkscape_mcp` against a running (or headless) Inkscape. Originally captured in the `svg-design` skill; consolidated here so it ships with the repo and is reachable independent of any per-client skill installation.

When the `inkscape_mcp` server is reachable and Inkscape is running, **prefer driving edits through the MCP** instead of hand-writing SVG. The MCP gives you precise geometric ops, live canvas feedback, and avoids the "I rewrote the whole file" failure mode for small tweaks.

Hand-author SVG when: the document doesn't exist yet, no Inkscape session is active, or you need a single-shot generation (icon, logo). Drive via MCP when: the file is already open, you're iterating, or you need an op Inkscape provides natively.

## Compose procedurally — the default design loop

Building a drawing as one blob of hand-written SVG is the failure mode this server exists to prevent: brittle hand-computed coordinates, no reuse, and a document the user can't edit afterwards. Build it up the way a designer would instead.

| Instead of… | Do this |
|---|---|
| Computing aligned/evenly-spaced coordinates by hand | `inkscape_vector` `align` (`operation_type="top"`, `"hcenter vcenter"`, `"top page"`) and `distribute` (`"hgap"`, `"vgap"`) |
| Writing one path that is really several shapes merged | Place the shapes, then `apply_boolean` (`union` / `difference` / `intersection` / `exclusion`), `path_combine`, `path_division`, `path_cut` |
| Copy-pasting the same geometry N times | `clone`, `tile_clone`, `object_to_marker`, `object_to_pattern`, or `<symbol>`/`<use>` — one edit updates every instance |
| Hand-authoring filter primitives | `inkscape_extension(operation="run_live", target=<id>)` with **no params**, after selecting the target; or `lpe_*` for path effects. Read the rendering-pitfalls section below before writing filters yourself |
| Outlining a stroke by hand | `stroke_to_path`; grow/shrink with `path_inset_outset` |
| Resizing the canvas by editing width/height | `fit_canvas_to_drawing`, `page_fit_to_selection` |

Two habits that make everything above work:

1. **Give every meaningful element a stable `id` as you create it.** Ids are the handle for every later edit — unaddressable geometry has to be rebuilt rather than adjusted.
2. **Work incrementally.** Each call is one Inkscape undo entry, so the user can step back through your work and co-edit alongside you.

## Look at your work

`rasterize` gives you eyes — render the document, a single element, or a region to PNG and read the image back. After any visual change, LOOK rather than assuming the SVG renders as intended: occlusion, clipped filter regions, invisible elements and colour mistakes only show up in the raster. When you need numbers instead of pixels, `inspect_element` returns the post-transform bbox and the fully-cascaded computed style.

## Work with the person at the keyboard

The canvas is shared, so collaborate rather than guess.

- **Ask them to select.** For an ambiguous target ("fix the spacing", "recolor this"), ask the user to select the object or group on canvas and read it back with `get_selection` / `inspect_selection`. Faster and far less error-prone than inferring intent from the XML.
- **Show them your candidate.** `set_selection` highlights what you're about to change on their canvas before you change it.
- **Open the UI for them.** When they ask where a setting lives, open it rather than describing a menu path — `apply_action("dialog-open", payload=<name>)`. Valid dialog names: `AlignDistribute`, `Clonetiler`, `DocumentProperties`, `Export`, `FillStroke`, `FilterEffects`, `Find`, `Glyphs`, `IconPreview`, `Input`, `LivePathEffect`, `Memory`, `Messages`, `ObjectAttributes`, `ObjectProperties`, `Objects`, `PaintServers`, `Selectors`, `Spellcheck`, `SVGFonts`, `Swatches`, `Symbols`, `Text`, `Trace`, `Transform`, `UndoHistory`, `XMLEditor`. Tools via `apply_action("tool-switch", payload=<name>)`: `Arc`, `Booleans`, `Calligraphic`, `Connector`, `Dropper`, `Eraser`, `Gradient`, `LPETool`, `Measure`, `Mesh`, `Node`, `PaintBucket`, `Pen`, `Pencil`, `Rect`, `Select`, `Spiral`, `Spray`, `Star`, `Text`, `Tweak`, `Zoom`. Both are read-only — they never modify the document.

## Picking the right operation

| You want to… | Use |
|---|---|
| Fire any of Inkscape's ~1244 verbs (selection, transforms, booleans, attribute edits, tool/dialog opening, layer ops, page ops, snap toggles, zoom/view) | `inkscape_live(operation="apply_action", target="<verb>", payload="<arg>")` |
| Discover the verb you need + its description | `inkscape_live(operation="list_actions", target="<substring>")` — returns `{app[{name, description}], window[{name, description}]}`. Filter is case-insensitive, matches name or description. Use `target="layer-"` for layer ops, `"snap"` for snapping, etc. |
| Insert new SVG geometry into the canvas | `inkscape_live(operation="insert_svg", payload="<svg fragment>")` |
| Structurally edit the XML (add to `<defs>`, restructure, rewrite `d` data, set arbitrary attribute on an arbitrary node) | `inkscape_live(operation="edit_xml", target="<xpath>", payload="<json>")` |
| Per-node bezier edits on a path (move node, set handle, smooth/cusp, insert node, subdivide) | `inkscape_live(operation="path_edit", target="<path-id>", payload="<json>")` |
| Read what the user has selected | `inkscape_live(operation="get_selection")` → `{count, ids, objects[{id,type,bbox}], text}` |
| Read the full document XML | `inkscape_live(operation="get_document_xml")` |
| Select something by id or CSS selector | `inkscape_live(operation="set_selection", target="<id-or-selector>")` |
| Check the bridge is live | `inkscape_live(operation="ping")` |

Default to `apply_action`. Use `edit_xml` when no Inkscape verb covers the edit (defs additions, structural rewrites, complex `d` math).

## Gotchas when firing actions

1. **`select-by-id` and `select-by-selector` are additive.** They don't replace the prior selection — they *add* to it. A subsequent `object-set-attribute` then mutates every still-selected element, not just the latest one. **Fire `apply_action("select-clear")` before each new selection.**
2. **`object-set-attribute` payload is `"attr,value"` (comma separator).** The value itself may contain commas — the action splits on the first comma only. So `points,900,216 892,212 892,220` parses as `attr=points`, `value=900,216 892,212 892,220`.
3. **There is no `delete-attribute` action.** Once you set a junk attribute via `apply_action`, it's there. Use `edit_xml` with `set_attr` to overwrite, or accept the cosmetic clutter (e.g. a stray `points` on a `<line>` is inert).
4. **Selection by CSS comma-list works.** `set_selection target="#a, #b, #c"` selects all three at once — useful for applying a common attribute to multiple elements in one call.
5. **Pattern-match on the selector heuristic.** Targets containing `#.[ >:,*` route through `select-by-selector` (CSS); plain identifiers route through `select-by-id`. Match the form to your intent.
6. **Make elements addressable.** When hand-authoring an SVG you plan to edit via MCP later, **give every meaningful element a stable `id`**. CSS attribute selectors (`polygon[points="..."]`) work too but are brittle.

## Structural XML edits via `edit_xml`

`edit_xml` wraps the entire save → mutate → reload sequence in one call. Handles dirty-doc detection, namespace propagation, and reload sequencing internally.

```
inkscape_live(
  operation="edit_xml",
  target='//svg:defs',                          # xpath; svg:/inkscape:/sodipodi:/xlink:/rdf:/dc: prefixes available
  payload='{"action":"append",
            "xml":"<filter id=\"shadow\">…</filter>"}'
)
```

Actions inside the JSON payload: `append` · `insert_before` · `insert_after` · `replace` · `remove` · `set_attr` (name, value) · `set_text` (text). Fragments inherit SVG/Inkscape namespaces automatically — no need to declare `xmlns=` per fragment.

**What `edit_xml` covers that `apply_action` can't:**

- Adding `<filter>`, `<marker>`, `<symbol>`, `<pattern>`, `<clipPath>` to `<defs>`.
- Editing path `d` data when the math is more complex than a single attribute set.
- Restructuring `<defs>` / `<metadata>` / Inkscape namespace blocks.
- Setting attributes on elements that lack ids and don't match a clean CSS selector.

> **Undo guarantee:** `edit_xml` routes through an inkex extension under the hood. Inkscape records each call as one undoable command, labeled **"MCP: Edit"** in the undo history. Ctrl+Z reverses the edit cleanly.

## Save semantics

Every MCP-driven mutation auto-saves to disk by default. That covers `apply_action` (mutating verbs), `insert_svg`, `delete_selected`, and `edit_xml`. Read-only verbs (selection changes, zoom/view, dialog/tool opening, `export-*`/`list-*`/`help-*`/`about-*`/`dialog-*` prefixes) don't trigger save.

Kill switch: `INKSCAPE_MCP_AUTO_SAVE=0` for batched-save behavior.

## Untitled docs

For Untitled documents (no saved path) the MCP auto-promotes them by saving to `~/.cache/inkscape_mcp/live-session-<pid>.svg` and re-opening. The original Untitled window stays open — close it manually.

## Operation cheat sheet

| Task | Call |
|---|---|
| Recolor selection | `apply_action(target="object-set-attribute", payload="fill,#cc3333")` |
| Rotate selection | `apply_action(target="transform-rotate", payload="45")` |
| Page rotate | `apply_action(target="page-rotate", payload="1")` — integer steps |
| Switch drawing tool | `apply_action(target="tool-switch", payload="Pen")` |
| Open a dialog | `apply_action(target="dialog-open", payload="DocumentProperties")` |
| Select by id | `set_selection(target="my-id")` |
| Select by CSS | `set_selection(target="#a, .b")` |
| Clear selection | `apply_action(target="select-clear")` |
| Insert geometry | `insert_svg(payload="<svg>…</svg>")` |
| Add filter to defs | `edit_xml(target="//svg:defs", payload='{"action":"append","xml":"<filter …/>"}')` |
| Edit path `d` directly | `edit_xml(target='//svg:path[@id="p1"]', payload='{"action":"set_attr","name":"d","value":"M 0 0 L 10 10"}')` |
| Replace an element | `edit_xml(target='//svg:rect[@id="r1"]', payload='{"action":"replace","xml":"<circle …/>"}')` |
| Move a path node | `path_edit(target="p1", payload='{"op":"move_node","node":[0,1],"to":[35,15]}')` |
| Set a node's in/out handle | `path_edit(target="p1", payload='{"op":"set_handle_in","node":[0,1],"to":[22,12]}')` |
| Insert a node mid-segment (t∈(0,1)) | `path_edit(target="p1", payload='{"op":"insert_node","segment":[0,0],"t":0.5}')` |
| Smooth / cusp a node (updates handles + `sodipodi:nodetypes`) | `path_edit(target="p1", payload='{"op":"smooth","node":[0,1]}')` |
| Subdivide every segment of a subpath (default: all subpaths) | `path_edit(target="p1", payload='{"op":"subdivide"}')` |
| Snapshot to scratch | `save_snapshot()` returns the scratch path |
| Read selection | `get_selection()` → `{count, ids, objects[{id,type,bbox}], text}` |
| Inspect one element (bbox + computed style + ancestors) | `inkscape_live(operation="inspect_element", target="<id>")` — bbox is post-transform document coords; `computed_style` is full CSS-cascade resolution (what the renderer actually uses); `ancestors` includes `is_layer` markers |
| Run arbitrary inkex Python | `inkscape_live(operation="execute_inkex", payload="<python>")` — globals: `svg`, `doc`, `inkex`, `etree`, `json`, `math`, `set_result(x)`. Assign to `result` or define `main()` returning a value. The broadest analytical + manipulation primitive — use for multi-element queries, geometric math, complex mutations not expressible via `apply_action`/`edit_xml`. One `MCP: Execute` undo entry (or `[unchanged]` if read-only). |
| Rasterize the doc / an element / an area to PNG | `inkscape_live(operation="rasterize", target="<id-or-empty>", payload='{"area":"x:y:w:h","dpi":192,"filename":"<abs>"}')` — defaults to a scratch path under `~/.cache/inkscape_mcp/`. Returns `{path, bytes}`. Gives the agent "eyes" for visual diff, occlusion, color sampling. |
| Discover installed extensions (system + user) | `inkscape_extension(operation="list")` — `target` is an optional substring filter |
| Inspect one extension's params | `inkscape_extension(operation="describe", target="<id>")` — returns the INX-declared param schema |
| Run an extension headlessly with custom params | `inkscape_extension(operation="run", target="<id>", params='<json>', input_path="<abs>", output_path?="<abs>")` |
| Apply an extension to the live doc | `inkscape_extension(operation="run_live", target="<id>", params='<json>')` — empty params route via D-Bus `.noprefs`; non-empty params render the extension on an **empty canvas** and append its output (wrapped in `<g id="mcp-ext-…">`) via a single `mcp_edit_xml` call. One `MCP: Edit` undo entry either way. The wrapper id comes back in the response — pass it to follow-up `edit_xml` calls to move/recolor/transform the inserted block. Only suits *generator* extensions (pdflatex, calendar, barcode, qr, gears) — transformer extensions on an empty canvas produce nothing and fail with a hint. |
| **Re-render** an extension in place (preserves CSS hooks / style rules referencing the id) | `inkscape_extension(operation="run_live", target="<ext-id>", params='<json>', wrapper_id="<existing-or-fresh-id>")` — when `wrapper_id` is supplied, any prior element with that id is removed and the new render uses the same id. Response surfaces `replaced_existing: true/false`. `wrapper_id` must match `^[A-Za-z][A-Za-z0-9_.\-]{0,63}$`. |

## Recipes for tools that used to be specialised

These were standalone MCP tools; folded into `apply_action` over the native Inkscape verb after the Phase 8 conservative prune. The agent composes the same outcomes from primitives.

### Clip / mask ops

| Operation | Recipe |
|---|---|
| Set clip on selection | `apply_action(target="object-set-clip")` |
| Release clip | `apply_action(target="object-release-clip")` |
| Inverse clip | `apply_action(target="object-set-inverse-clip")` |
| Set mask | `apply_action(target="object-set-mask")` |
| Release mask | `apply_action(target="object-release-mask")` |
| Inverse mask | `apply_action(target="object-set-inverse-mask")` |

Typical sequence: `set_selection(target="<clip-shape-id>, <target-id>")` then `apply_action(target="object-set-clip")`.

### Layer & selection refinement

| Operation | Recipe |
|---|---|
| Select by id | `set_selection(target="<id>")` |
| Select by CSS selector | `set_selection(target="<selector>")` |
| Select by element type | `apply_action(target="select-by-element", payload="<tag>")` |
| Select by class | `apply_action(target="select-by-class", payload="<class>")` |
| Invert selection | `apply_action(target="select-invert")` |
| Select all | `apply_action(target="select-all")` |
| Hide / unhide selection | `apply_action(target="selection-hide")` / `selection-unhide` |
| Lock / unlock selection | `apply_action(target="selection-lock")` / `selection-unlock` |

### Render generators

| Operation | Recipe |
|---|---|
| Calendar | `inkscape_extension(operation="run_live", target="org.inkscape.render.calendar")` (defaults) — or with params for year/month |
| Barcode | `apply_action(target="org.inkscape.render.barcode.noprefs")` |
| Data matrix | `apply_action(target="org.inkscape.render.data-matrix.noprefs")` |
| Foldable box | `apply_action(target="org.inkscape.render.foldable-box.noprefs")` |
| Cartesian grid | `apply_action(target="org.inkscape.render.grid-cartesian.noprefs")` |
| Isometric grid | `apply_action(target="org.inkscape.render.grid-isometric.noprefs")` |
| 3D polyhedron | `apply_action(target="org.inkscape.render.poly-3d.noprefs")` |
| Rack gear | `apply_action(target="org.inkscape.render.rack-gear.noprefs")` |

For custom params (e.g. calendar year/month): use `inkscape_extension(operation="describe", target="org.inkscape.render.calendar")` to see param names, then `run_live(target=..., params='{"year":2026,...}')`.

## Inkscape rendering pitfalls (MCP-relevant)

These are Inkscape-specific quirks that bite MCP-authored content. The output files are *valid SVG* and render correctly in browsers / image viewers; only Inkscape's editor preview shows the symptoms.

### `feDropShadow` is silently broken in Inkscape 1.4 preview

`<feDropShadow>` is valid SVG 2. Inkscape 1.4.4 (Ubuntu PPA build, 2026-05-06) **silently hides** any element with a filter that contains it. No error, no fallback to the unfiltered source.

**Workaround — use the classic SVG 1.1 drop-shadow recipe instead:**

```xml
<filter id="dropshadow" x="-0.3" y="-0.3" width="1.6" height="1.6" inkscape:auto-region="false">
  <feGaussianBlur in="SourceAlpha" stdDeviation="3"/>
  <feOffset dx="0" dy="4"/>
  <feComponentTransfer><feFuncA type="linear" slope="0.5"/></feComponentTransfer>
  <feMerge>
    <feMergeNode/>
    <feMergeNode in="SourceGraphic"/>
  </feMerge>
</filter>
```

`stdDeviation` = blur radius, `dy` = shadow offset, `slope` = shadow opacity.

### `inkscape:auto-region` silently clamps filter bounds

Inkscape auto-rewrites filter `x`/`y`/`width`/`height` to fit the source bbox precisely — so `x="-0.3" width="1.6"` becomes `x="-0.01" width="1.02"`. The shadow then renders outside the now-tiny filter region and gets clipped.

**Always set `inkscape:auto-region="false"` on filters authored via the MCP.** Required when shadows or blurs need margin around the source.

### Empty-string attribute values delete the attribute (since `PLUGINS_VERSION=8`)

`edit_xml(set_attr, value="")` deletes the named attribute rather than writing `attr=""`. This is the canonical "absent" form and avoids the Inkscape 1.4 invisibility bug where empty-string `filter=""` hid the element. To explicitly set `value="none"` (e.g. for `filter="none"`), pass that literal string. Pre-v8 behaviour wrote the empty string and tripped the renderer — upgrade if you're on v7 or earlier.

### Recoloring extension output via CSS needs to discriminate fg from bg

Generator extensions don't all paint the same way. Two patterns that need different CSS selectors:

**Pdflatex / text-heavy output** — glyphs have explicit `fill="#000000"` on inner groups; some use `stroke` for fraction bars / integral decorations. Set both, but limit stroke to elements that already have one (so unstroked glyphs don't visually thicken):

```xml
<style>
  #my-equation * { fill: #f472b6 !important; }
  #my-equation [stroke] { stroke: #f472b6 !important; }
</style>
```

**QR codes / barcodes / similar 2-color generators** — modules are paths, background is a white `<rect>`. `* { fill }` recolors **both** → solid block. Use element-specific selectors:

```xml
<style>
  /* recolours the QR modules but leaves the white background alone */
  #my-qr path { fill: #cc3333 !important; }
</style>
```

If unsure, `rasterize` the result to see what the recoloring actually did — then narrow the selector based on what looks wrong.

### `//svg:defs` matches every `<defs>` element, including nested ones

`edit_xml(target="//svg:defs", action="append", ...)` appends the fragment to **all** matching defs — and SVG docs frequently have a nested `<defs>` inside any extension-rendered wrapper (pdflatex emits `<defs id="defs1">` containing glyph paths). Inkscape silently renames any duplicate ids in the second copy, leaving a leftover element you didn't intend.

Use a precise target instead:

| Goal | xpath |
|---|---|
| Append to the root doc's defs only | `//*[@id='defs110']` (or whatever its id is — `inspect_defs` reports it) |
| Append to the SVG-root-level defs without relying on id | `/svg:svg/svg:defs` |
| Append to a specific wrapper's defs | `//*[@id='<wrapper-id>']/svg:defs` |

### Multi-window auto-detect (since `PLUGINS_VERSION=8`)

`inkscape_live` now auto-detects the active window. If you pass `window_id=1` (the default) but window 1 isn't open, the tool falls back to the first available window from `bus.list_windows()`. The earlier failure mode — `Object does not exist at path /org/inkscape/Inkscape/window/1` when the user closes a doc — is gone.

You can still pass `window_id` explicitly to target a specific window when multiple are open.

## When the bridge is down

`ping` returns `success: False` if no GUI is running; other live ops return `bridge unavailable`. Fall back to the headless tools — `inkscape_file`, `inkscape_vector`, `inkscape_extension(operation="run", ...)` — which work without the GUI.
