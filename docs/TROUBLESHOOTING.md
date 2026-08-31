# Troubleshooting

Tested with Inkscape 1.4.4 on Ubuntu 24.04.

## Installation

### Inkscape not found

`inkscape_system(operation="diagnostics")` reports `inkscape_available: false`.

- Confirm with `inkscape --version` on the same `$PATH` as the MCP server process.
- Override with `INKSCAPE_BIN=/path/to/inkscape` in the server env. When set, it wins —
  `$PATH` auto-detection only runs if nothing pins the binary. Check which one won with
  the `config_sources` block of `inkscape_system(operation="diagnostics")`.
- Inkscape 1.4.x is the supported line; older releases are not.

### `uv sync` fails building pycairo / pygobject

Install the system dev headers:

```bash
sudo apt install libcairo2-dev libgirepository-2.0-dev libgirepository1.0-dev pkg-config python3-dev
```

`libgirepository-2.0-dev` is required by `pygobject>=3.56`; the older `1.0-dev` alone is not enough on Ubuntu 24.04.

### Python version

Requires **Python 3.12+** per `pyproject.toml`. Check with `python3 --version`.

## Runtime

### Operation timed out

- Increase `process_timeout` in config (default 30s).
- For large batches, lower `max_concurrent_processes` so each subprocess has more breathing room.
- D-Bus `inkscape_live` operations have their own timeout — see the `payload` for the specific op.

### File not found / permission denied

- Use absolute paths; the agent's working directory is rarely what you expect.
- Confirm the path resolves under one of `allowed_directories` in the server config.
- Check that the file is readable by the user running the MCP server.

### Invalid SVG

- Run `inkscape_analysis(operation="validate", input_path=...)` first.
- Check namespace declarations; Inkscape is strict about malformed `<svg>` roots.

### GUI/CLI profile lock

If the GUI is open while a CLI invocation runs, the second process may block on the profile. Set `INKSCAPE_PROFILE_DIR` in the MCP server env to a dedicated directory so the CLI gets its own profile:

```bash
export INKSCAPE_PROFILE_DIR="$HOME/.config/inkscape_mcp/inkscape-profile"
```

The directory is created on first run.

### Missing optional system packages

Some export and trace operations need extra packages:

- `ghostscript` for PS/EPS export.
- `poppler-utils` for PDF import.
- `potrace` for bitmap tracing (`trace_image`).

## D-Bus / live canvas

### `inkscape_live` reports the bridge is unavailable

- Inkscape must already be running.
- `inkscape_system(operation="diagnostics")` reports `bridge.live` and `bridge.needs_restart`. If `needs_restart` is `true`, the server just installed or updated its inkex plugins — close and reopen Inkscape so it picks them up.
- The MCP server auto-installs plugins to `~/.config/inkscape/extensions/inkscape_mcp/` on first boot. Inkscape only scans the extensions dir at startup.

### Clipboard insert (`insert_svg`) fails

- X11: `xclip` must be on PATH.
- Wayland: `wl-clipboard` is preferred, but `xclip` also works — Inkscape runs as an
  XWayland client, so the server falls back to it when `wl-copy` is absent.
- The server auto-detects; if both are missing the operation surfaces a clear error.

## Extensions

### Extension not found

- Confirm with `inkscape_extension(operation="list")`.
- Inkscape only scans extension directories at startup; restart Inkscape if you just installed a new extension.

### Extension execution failed

- Inspect the parameter schema with `inkscape_extension(operation="describe", target="<id>")` and confirm your `params` JSON matches.
- For `run_live`, check that the live canvas has the expected selection / element ids.

## Performance

- Live D-Bus operations are dramatically faster than CLI invocations for repeated small edits — Inkscape startup is the main cost.
- For batch CLI work, drop `max_concurrent_processes` if you're memory-bound; raise it if you're throughput-bound.

## Logging and diagnostics

The first thing to do for any failure is:

```python
inkscape_system(operation="diagnostics")
```

It reports Inkscape reachability, config provenance under `config_sources` (whether each value came from a CLI flag, env var, config file, `$PATH` auto-detection, or the built-in default), and the D-Bus bridge state.

Set `INKSCAPE_MCP_LOG_LEVEL=DEBUG` for verbose logs to stderr.

## Reporting issues

When opening a GitHub issue, include:

- Inkscape version (`inkscape --version`).
- Python version (`python3 --version`).
- OS / distro version.
- The full failing tool call (operation + parameters).
- Output of `inkscape_system(operation="diagnostics")`.
- Stderr from the MCP server.
