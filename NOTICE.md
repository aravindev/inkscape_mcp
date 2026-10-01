# NOTICE

## Project lineage

This project is a fork of **`sandraschi/inkscape-mcp`**
(<https://github.com/sandraschi/inkscape-mcp>) by Sandra Schipal. That
upstream project was itself bootstrapped from
**`sandraschi/gimp-mcp`** — the initial commit in this fork's history is
labelled "Initial commit — basic structure from gimp-mcp template" and
the Inkscape-specific code landed in subsequent commits.

This fork was first developed for Linux (Ubuntu 24.04, Inkscape 1.4.4). The upstream
targeted Windows first and did not run on Linux without patching; Windows-specific
compatibility, the original test harness, and unused scaffolding were removed. macOS and
Windows live-bridge support were added later (see below).

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

## Windows live support contribution

Windows support for the live bridge (2026, Ergin Atalar) restores the cross-platform
reach that this Linux fork had removed. It adds `win_dbus_client.py` and `bus_manager.py`
and platform-aware branches in `tools/live.py`, `clipboard.py`, and
`extension_bridge.py`. The live bridge is driven through
Inkscape's bundled `gdbus.exe` over a managed D-Bus session bus rather than the Linux
`jeepney`/`xclip` path. Contributed under the same MIT License; Linux/macOS behaviour is
unchanged.

## Cross-platform live bridge, security hardening, layers and animation (2026)

Contributed by **radhikrammohan** (<https://github.com/radhikrammohan>), with AI assistance from Claude Code.

This contribution builds on the project above and draws ideas from two other MIT-licensed
projects. In each case the code was written for this codebase; nothing was copied verbatim, and
where a design is borrowed it is named here.

**Cross-platform live bridge (original work).** `embedded_bus.py` (a minimal pure-Python D-Bus
session bus), `bus_connect.py`, `live_session.py` and `platform_paths.py`, plus per-OS Inkscape and
extension-directory detection in `inkscape_detector.py`. This replaces the need for a system
`dbus-daemon` (MSYS2 on Windows, Homebrew on macOS), works around a macOS incompatibility in
jeepney's connection handshake, and handles macOS-specific Inkscape 1.4.2 behaviour (no exported
window objects; a crash when extensions run with a very large open-file limit). Verified on macOS;
the Windows TCP path is implemented but has not been run on real hardware.

**Security hardening** (`security.py`, `proc_utils.py`, parts of `cli_wrapper.py`). The following
ideas come from **`grumpydevorg/inkscape-mcps`** (MIT, Copyright (c) 2025 Inkscape MCP Server,
<https://github.com/grumpydevorg/inkscape-mcps>): confining paths to a configured workspace,
a file-size limit, an allowlist of safe actions, writing exports to a temporary file and moving it
into place, terminating the whole process group on timeout, and a concurrency limit. They are
re-implemented here around this server's async wrapper, applied through a single FastMCP middleware
rather than per-tool checks, and extended (JSON-embedded paths, symlink handling, action-chain
injection checks, a strict mode, atomic writes for chain-embedded export paths).

**Layers and animation** (`tools/layers.py`, `tools/animation.py`). The operation sets and the preset
catalogue come from **`sandraschi/inkscape-mcp`** (MIT, Copyright (c) 2026 Sandra Schipal), the
upstream of this fork; layer management had been dropped from this fork. They are rewritten on a real
XML tree instead of text and regular-expression editing, which fixes nested-layer matching, unescaped
labels and markup injection, and makes every animation operation act on an element of the user's file.
Sandraschi's Live Path Effect tools were deliberately **not** ported: its `apply_lpe` calls actions
(`org.inkscape.effect.<id>`, `lpe-param-set`) that do not exist in Inkscape 1.4, and path effects do
not compute headlessly at all (verified against Inkscape 1.4.2).

All new code is contributed under the MIT License of this project.
