# NOTICE

## Project lineage

This project is a fork of **`sandraschi/inkscape-mcp`**
(<https://github.com/sandraschi/inkscape-mcp>) by Sandra Schipal. That
upstream project was itself bootstrapped from
**`sandraschi/gimp-mcp`** — the initial commit in this fork's history is
labelled "Initial commit — basic structure from gimp-mcp template" and
the Inkscape-specific code landed in subsequent commits.

This fork targets Linux (developed and tested on Ubuntu 24.04 with
Inkscape 1.4.4). The upstream targeted Windows first and did not run on
Linux without patching; Windows-specific compatibility, the original
test harness, and unused scaffolding have been removed.

## Acknowledgement

- **Upstream**: `sandraschi/inkscape-mcp` — Sandra Schipal
  (<sandra@sandraschi.dev>), with the FastMCP Community as co-credit.
- **Original template**: `sandraschi/gimp-mcp` — same author.
- Both upstream projects are distributed under the MIT License.

The MIT License permits free use, modification, and redistribution
provided the copyright notice and permission notice are included with
substantial portions of the original software. This file preserves that
acknowledgement; the actual MIT permission text from upstream should be
reproduced when a project-level LICENSE is added (see "License of this
project" below).

## Scope of remaining upstream code

The project has been substantially rewritten since the fork. Residual
upstream code is concentrated in scaffolding modules — `__init__.py`,
`logging_config.py`, `tool_utils.py`, and `config.py` — and partial
fragments of `main.py`, `server.py`, `cli_wrapper.py`, and a few tool
stubs (`tools/file_operations.py`, `tools/analysis.py`, `tools/system.py`,
`tools/layer.py`).

New code authored for this fork includes the D-Bus live-bridge
(`dbus_client.py`, `tools/live.py`, `extension_bridge.py`, `clipboard.py`),
the bundled `inkex` extensions (`plugins/mcp_echo`, `mcp_edit_xml`,
`mcp_inspect`, `mcp_path_edit`), the extension runner (`tools/extension.py`),
the gradient/metadata/heraldry/clipmask tool surfaces, and the
prompts/resources/prefab infrastructure.

## Third-party frameworks and runtime dependencies

- **FastMCP** by Jeremiah Lowin — <https://github.com/jlowin/fastmcp>,
  Apache-2.0. Provides the MCP server framework.
- **Inkscape** and **inkex** — <https://inkscape.org>, GPL-2.0. Inkscape
  is invoked as an external process; the bundled extensions in
  `src/inkscape_mcp/plugins/` import `inkex` at runtime when Inkscape
  executes them as subprocesses.

## License of this project

This project is distributed under the MIT License — see [`LICENSE`](LICENSE).
That is the same license as the upstream `sandraschi/inkscape-mcp` and
`sandraschi/gimp-mcp` projects, so the entire derivative chain is covered
by consistent terms.
