# Windows live support

This document describes the Windows support for the **live** Inkscape bridge
(`inkscape_live`). The headless CLI tools (`inkscape_file`, `inkscape_vector`,
`inkscape_analysis`, `inkscape_gradient`, `inkscape_metadata`) already work on Windows
because they shell out to `inkscape.exe`. This adds the missing piece: driving a
**running Inkscape GUI** live, focus-free, so an agent and a human can co-edit the same
document.

## How the Windows path works

| Concern | Linux (existing) | Windows (this change) |
|---|---|---|
| Transport | `jeepney` over the unix session bus | `gdbus.exe` (ships with Inkscape) over a TCP session bus |
| Session bus | provided by the desktop | a private `dbus-daemon` the MCP manages |
| Reaching the GUI | the user's running Inkscape | an Inkscape the MCP launches **under the bus** |
| Window/doc object path | `/org/inkscape/Inkscape/window/N` | `/org/inkscape/Inkscape/document/N` (Inkscape 1.4.x) |
| SVG insertion | clipboard + `paste-in-place` | `mcp_execute` extension (1.4.x exposes no paste action over D-Bus) |
| Extensions dir | `~/.config/inkscape/extensions` | `%APPDATA%\inkscape\extensions` |

New/changed modules:

- **`win_dbus_client.py`** — `WinInkscapeDBus`, a drop-in for `InkscapeDBus` that drives
  the action surface by shelling out to `gdbus.exe`.
- **`bus_manager.py`** — starts/reuses a `dbus-daemon` session bus and launches Inkscape
  under it (opening a blank canvas so a document window exists), all lazily and
  detached so it survives MCP restarts.
- **`tools/live.py`** — platform-aware `_get_bus()`, Windows auto-launch, and an
  inkex-based `insert_svg`.
- **`clipboard.py`** — a Win32 clipboard-staging branch (registers the
  `image/x-inkscape-svg` format).
- **`extension_bridge.py`** — platform-aware install path for the bundled `mcp_*`
  plugins.

Linux/macOS behaviour is unchanged — every Windows branch is guarded by
`sys.platform` / `bus_manager.is_windows()`.

## Prerequisites

1. **Windows 10/11**.
2. **Inkscape 1.4.x** (tested on 1.4.4). `gdbus.exe` ships beside `inkscape.exe`, so no
   extra GLib install is needed.
3. **A Windows `dbus-daemon`.** The easiest source is MSYS2:

   ```sh
   pacman -S mingw-w64-x86_64-dbus
   ```

   This installs `C:\msys64\mingw64\bin\dbus-daemon.exe`, which the MCP finds
   automatically. All of its dependency DLLs already ship with Inkscape. If you put it
   elsewhere, set `INKSCAPE_MCP_DBUS_DAEMON` to its full path.

## Install & configure

Install the server:

```sh
git clone https://github.com/aravindev/inkscape_mcp
cd inkscape_mcp
uv venv
uv pip install -e .
```

Point your MCP client at it. Example for a Claude config (`mcpServers`):

```json
{
  "inkscape": {
    "command": "C:\\path\\to\\inkscape-mcp-windows\\.venv\\Scripts\\inkscape-mcp.exe",
    "args": [],
    "env": {
      "INKS_INKSCAPE_BIN": "C:\\Program Files\\Inkscape\\bin\\inkscape.exe",
      "INKSCAPE_MCP_AUTO_SAVE": "0"
    }
  }
}
```

Or run it straight from the repo with `uvx`:

```sh
uvx --from git+https://github.com/aravindev/inkscape_mcp inkscape-mcp
```

### Environment variables

| Variable | Purpose |
|---|---|
| `INKS_INKSCAPE_BIN` | Path to `inkscape.exe` (auto-detected otherwise; `.COM` is normalised to `.exe`). |
| `INKSCAPE_MCP_AUTO_SAVE` | `0` to never auto-save after edits (recommended when co-editing), `1`/unset to save. |
| `INKSCAPE_MCP_DBUS_DAEMON` | Override the `dbus-daemon.exe` location. |
| `INKSCAPE_MCP_GDBUS` | Override the `gdbus.exe` location. |

## The shared-canvas model

`live` means **the Inkscape window the MCP manages**, not a separate one you launch by
hand. On the first live operation the MCP:

1. starts (or reuses) a private `dbus-daemon`,
2. launches Inkscape under that bus on a blank canvas, and
3. connects over `gdbus`.

From then on you and the agent work the **same document**: the agent's edits and your
manual edits interleave on one undo stack (each MCP edit is a single undoable command),
and the transport is **focus-free** — it never steals focus or injects keystrokes while
you are editing.

> **Important:** a normally-launched Inkscape (double-click, Start menu) is *not* on the
> managed bus and is invisible to the MCP. To work on a specific file, have the MCP open
> it (`inkscape_live` `open_file`) so it lands in the shared window.

## Supported live operations

All `inkscape_live` operations work on Windows:

- **Actions & selection:** `ping`, `list_actions` (1075 app + 474 document actions on
  1.4.4), `apply_action`, `set_selection`, `delete_selected`, `open_file`.
- **Read-back & raster:** `get_document_xml`, `save_snapshot`, `rasterize`.
- **Structural editing (via bundled inkex plugins):** `insert_svg`, `edit_xml`,
  `path_edit`, `inspect_selection` / `inspect_layers` / `inspect_defs` /
  `inspect_view` / `inspect_pages` / `inspect_element`, `get_selection`,
  `execute_inkex`.

`insert_svg` is implemented by appending the fragment's children to the document through
the `mcp_execute` extension, because Inkscape 1.4.x exposes no paste/import-file action
over D-Bus.

## Limitations & notes

- **External `dbus-daemon` dependency.** The MCP does not yet bundle one; install it via
  MSYS2 (above). Bundling it in the package is a possible future improvement.
- **The MCP manages its own Inkscape instance.** It cannot attach to an Inkscape you
  launched yourself (that one isn't on the bus).
- **Tested on Inkscape 1.4.4.** The `/document/N` object path and the absence of a paste
  action are version-specific; older/newer Inkscape may differ.

## Troubleshooting

- **"dbus-daemon not found"** — install `mingw-w64-x86_64-dbus` via MSYS2 or set
  `INKSCAPE_MCP_DBUS_DAEMON`.
- **"Inkscape D-Bus bridge not reachable"** after a live op — the auto-launch waits up to
  ~25 s for Inkscape to open a document window; a very cold first start (extension
  scanning) can exceed that. Retry the operation.
- **Edits aren't appearing in your window** — you are probably looking at a
  hand-launched Inkscape. Use the MCP-managed window (the one auto-opened on the blank
  canvas), or have the MCP `open_file` your document.
- **Plugins not registering** — the bundled `mcp_*` extensions install to
  `%APPDATA%\inkscape\extensions\inkscape_mcp` on server start; Inkscape registers them
  only at launch, so they appear in the MCP-launched instance.
