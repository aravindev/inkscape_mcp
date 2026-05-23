# Installation

Linux only. Tested with Inkscape 1.4.4 on Ubuntu 24.04.

## Prerequisites

```bash
# Inkscape itself
sudo add-apt-repository ppa:inkscape.dev/stable
sudo apt update
sudo apt install inkscape

# Build deps for the Python extensions pulled in by inkex / pygobject
sudo apt install libcairo2-dev libgirepository-2.0-dev libgirepository1.0-dev pkg-config python3-dev
```

You also need **Python 3.12+** and **[uv](https://docs.astral.sh/uv/install/)**.

## Clone + build

```bash
git clone https://github.com/aravindev/inkscape_mcp.git ~/git/inkscape_mcp
cd ~/git/inkscape_mcp
uv sync
```

Smoke-test the server:

```bash
uv run inkscape_mcp --help
```

## Register with Claude Code

```bash
claude mcp add inkscape_mcp -s user -- uv --directory ~/git/inkscape_mcp run inkscape_mcp
claude mcp list | grep inkscape_mcp   # should show "✓ Connected"
```

## Override the Inkscape binary

If you want to pin a non-default Inkscape build:

```bash
export INKSCAPE_BIN=/opt/inkscape-nightly/bin/inkscape
```

Inspect from the agent with `inkscape_system(operation="diagnostics")`.

## Next

- [INKSCAPE.md](INKSCAPE.md) — Inkscape install details and CLI verification.
- [USAGE.md](USAGE.md) — calling tools.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common build/runtime errors.
