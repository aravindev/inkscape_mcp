# Usage

Agents interact with **MCP tools**, not Python functions in your notebook. The server exposes **portmanteau** tools: each tool takes an `operation` string and paths/parameters.

Full parameter detail: [API.md](API.md). Install: [INSTALL.md](INSTALL.md). Inkscape: [INKSCAPE.md](INKSCAPE.md).

## Tools at a glance

| Tool | Role |
|------|------|
| `inkscape_file` | `load`, `save`, `convert`, `info`, `validate`, `list_formats`, `batch_convert` |
| `inkscape_vector` | trace, boolean, simplify, optimize, render, QR, layout, LPE, cloning, text (47 ops) |
| `inkscape_analysis` | `quality`, `statistics`, `validate`, `objects`, `dimensions`, `structure` |
| `inkscape_system` | `status`, `help`, `diagnostics`, `version`, `config`, `list_extensions`, `execute_extension` |
| `inkscape_extension` | `list`, `describe`, `run`, `run_live` — discover and invoke installed inkex extensions |
| `inkscape_gradient` | gradient-stop manipulation; linear↔radial conversion |
| `inkscape_metadata` | Dublin-Core RDF metadata (title, creator, description, rights, keywords) |
| `inkscape_live` | drive the running Inkscape GUI via D-Bus (20 ops including `rasterize`) |

## Natural language → tool

Ask in plain language; the model should map to the right tool and `operation`. Examples:

- “Validate `logo.svg` and tell me width and height.” → `inkscape_file` / `inkscape_analysis`
- “Export `diagram.svg` to `diagram.pdf`.” → `inkscape_file` `convert`
- “Trace `scan.png` to `scan.svg`.” → `inkscape_vector` `trace_image`
- “Is Inkscape available?” → `inkscape_system` `status`

## JSON shape (illustrative)

Exact fields match the tool signatures in code; this is a typical pattern:

```json
{
  "operation": "convert",
  "input_path": "/path/to/in.svg",
  "output_path": "/path/to/out.pdf",
  "format": "pdf"
}
```

For `inkscape_vector`, include `input_path` and, when needed, `output_path`, `object_id`, `operation_type`, etc.

## Safe habits

- Prefer **absolute paths** if the client’s working directory is unclear.
- **Confirm overwrites** before `convert` or destructive vector ops.
- Run **`status`** or **`validate`** before long batches.

## Config

Optional YAML or env-based settings (Inkscape path, timeouts). See server help output and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
