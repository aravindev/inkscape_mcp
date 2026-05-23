# Architecture

## Overview

**inkscape_mcp** is a **FastMCP 3.2+** server. Tools are implemented in Python; heavy work is delegated to the **Inkscape CLI** (queries and `--actions` chains) or to the running Inkscape GUI via **D-Bus**. The package lives under `src/inkscape_mcp/`.

## Core components

### FastMCP layer

- **Tool surface:** 8 portmanteau tools (see [TOOLS.md](TOOLS.md))
- **Transports:** stdio (default) and MCP-streamable HTTP — see `transport.py` and CLI flags on `inkscape_mcp.main`
- **Prompts and resources:** registered in `prompts_resources.py`
- **Responses:** JSON-friendly dicts (`success`, `message`, `data`, `execution_time_ms`, `error`)

### CLI integration (`cli_wrapper.py`)

- **Detection:** `inkscape_detector.py` resolves the Inkscape binary from `INKSCAPE_BIN`, PATH, and well-known Linux install locations.
- **Process management:** every spawn enforces `process_timeout` and a bounded concurrency cap from `InkscapeConfig`.
- **Action chaining:** stateful operation sequences using Inkscape's `--actions=` API.
- **Output processing:** stderr/stdout decoding, error normalization.

### D-Bus bridge (`dbus_client.py`, `extension_bridge.py`, `clipboard.py`)

- **Live document control:** `inkscape_live` talks to a running Inkscape instance over the D-Bus session bus.
- **Inkex helpers:** `extension_bridge.py` installs the server's own inkex plugins (`plugins/`) into `~/.config/inkscape/extensions/inkscape_mcp/` on first boot; Inkscape only scans the extensions dir at startup, so a restart is required after install.
- **Clipboard staging:** SVG fragments are inserted into the live canvas through `xclip` (X11) or `wl-clipboard` (Wayland), auto-detected.

### Extension system (`tools/extension.py`, `plugins/`)

- **Discovery:** scans Inkscape extension directories on the filesystem.
- **Parameter introspection:** parses `.inx` manifests to build a schema the agent can fill in.
- **Headless and live execution:** `run` calls the extension on a file; `run_live` calls it on the open document.

## Data flow

1. **Request:** FastMCP routes a tool call to the portmanteau function in `main.py`.
2. **Validation:** Pydantic + `Literal[...]` operation enums (`mcp_tool_types.py`) reject bad input at parse time.
3. **Dispatch:** the per-tool function in `tools/` selects the CLI or D-Bus path.
4. **Execution:** `InkscapeCliWrapper` spawns Inkscape (or the D-Bus client sends a message) with a per-process timeout.
5. **Response:** result is serialized into the standard dict envelope and returned over the MCP transport.

## Security model

- **Path gating:** writes/reads must resolve under `allowed_directories`.
- **Process isolation:** every CLI invocation is its own subprocess with its own timeout.
- **No network surface:** the server has no built-in HTTP API beyond MCP-streamable HTTP itself.

## Performance

Depends on Inkscape startup, file size, and path complexity. Tune `process_timeout` and `max_concurrent_processes` in config when batching. Live operations through D-Bus avoid Inkscape startup entirely and are much faster than CLI for repeated small edits.

## Platform support

**Linux only.** Tested with Inkscape **1.4.4** on Ubuntu 24.04. Older Inkscape versions are not supported. Python **3.12+** per `pyproject.toml`.

## Configuration System

YAML-based configuration with environment variable support:

```yaml
# Inkscape settings
inkscape_executable: auto  # Auto-detected
working_directory: "/tmp/inkscape_mcp"

# Performance tuning
max_concurrent_processes: 3
process_timeout: 30
max_file_size_mb: 100

# Extensions
extension_directories:
  - "~/.config/inkscape/extensions"
  - "/usr/share/inkscape/extensions"
```

## Errors

Tools return structured failure payloads (messages, error types). Timeouts and Inkscape stderr propagate through the CLI wrapper — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
