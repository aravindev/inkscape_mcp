# Features

MCP server that drives Inkscape 1.4.4 from an AI agent — either
headlessly through the CLI or live alongside a running Inkscape window via
D-Bus. Built on FastMCP 3.2.

## What the agent can do

### Live canvas (Inkscape running)

- Read the current selection, layer structure, defs, view, pages.
- Apply any of ~1,070 Inkscape actions on the live document — each one a
  normal undo entry.
- Insert SVG fragments at the cursor (clipboard-staged).
- Edit element attributes and path `d` data in place.
- Rasterize the document or a single element to PNG so the agent can *see*
  the result and iterate.
- Run any installed inkex extension against the open document.

### Headless / file workflows

- Convert SVG to PDF, PNG, EPS, PS, and the rest of Inkscape's export
  formats.
- Validate and inspect SVGs without opening the GUI.
- Boolean operations, path simplification, optimization, tracing of raster
  art, barcode and QR generation, mesh gradients, LPE chains, tile clones.
- Layer-to-files export, DXF export, fit-canvas-to-drawing.

### Extension ecosystem

- Discover and run any of Inkscape's bundled 200+ inkex extensions.
- The server auto-installs its own inkex plugins to
  `~/.config/inkscape/extensions/inkscape_mcp/` on first boot so the live
  bridge has the helpers it needs.

### Document metadata

- Read and write Dublin-Core RDF metadata (title, creator, description,
  rights, keywords).

### Gradients

- Add, remove, recolor, and reorder stops on linear and radial gradients;
  convert between linear and radial.

## Tool surface

Eight portmanteau tools — each takes an `operation` string that picks the
behavior, so the agent sees a compact catalog instead of dozens of
single-purpose tools.

| Tool | Operations | Purpose |
|------|-----------:|---------|
| `inkscape_file`      |  7 | Load, save, convert, info, validate, list formats, batch convert. |
| `inkscape_vector`    | 47 | Boolean, path, trace, optimize, render, barcode/QR, layout, LPE, cloning, text. |
| `inkscape_analysis`  |  6 | Quality, statistics, validate, objects, dimensions, structure. |
| `inkscape_system`    |  7 | Status, help, diagnostics, version, config, list/execute extensions. |
| `inkscape_extension` |  4 | Discover and invoke installed inkex extensions (headless or live). |
| `inkscape_gradient`  |  6 | Gradient-stop manipulation; linear↔radial conversion. |
| `inkscape_metadata`  |  6 | Read/write Dublin-Core RDF metadata. |
| `inkscape_live`      | 20 | Drive the running Inkscape window via D-Bus. |

Full operation list per tool in [TOOLS.md](TOOLS.md). Schema parameters in
[API.md](API.md).

## How it's delivered

- **Transports:** stdio (default, for Claude Code / Claude Desktop) and
  MCP-streamable HTTP (path `/mcp`) via FastMCP.
- **Discovery:** MCP prompts and resources expose the captured Inkscape
  1.4.4 `--action-list` and `--help` so agents can browse the underlying
  surface without shelling out.
- **Async:** every Inkscape invocation runs through an async CLI wrapper
  with a configurable per-process timeout.
- **Validation:** Pydantic models enforce parameter shapes; the operation
  enum on each portmanteau is a `Literal[...]` so wrong operation strings
  fail at parse time.

## Scope

Tested with Inkscape 1.4.4 on Ubuntu 24.04. Older Inkscape releases are
not supported.
