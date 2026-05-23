# Inkscape application

The MCP server shells out to **Inkscape**. If the CLI is missing or wrong, every tool fails.

## Install Inkscape

Tested with Inkscape **1.4.4** on Ubuntu 24.04. Older versions (including the 1.2.2 Ubuntu default) are not supported.

```bash
sudo add-apt-repository ppa:inkscape.dev/stable
sudo apt update
sudo apt install inkscape
```

Snap and Flatpak builds also work as long as the `inkscape` command is on the same `$PATH` as the MCP server process.

## Verify the CLI

In the same shell environment the MCP server will run in:

```bash
inkscape --version
```

You should see `Inkscape 1.4.x`.

## Configuration

- **Auto-detect:** the server checks `$PATH` and a small set of fallback locations (`/usr/bin/inkscape`, `/snap/bin/inkscape`, the Flatpak export, `~/.local/bin/inkscape`).
- **Override:** set the `INKSCAPE_BIN` env var, or `inkscape_executable` in `~/.config/inkscape_mcp/config.yaml`. Both are reported by `inkscape_system(operation="diagnostics")`.

## Limitations

Not every Inkscape feature is exposed as a CLI action. If an operation returns "not implemented" or fails, use the GUI for that step or open an issue with the exact action and version.
