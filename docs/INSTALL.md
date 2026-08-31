# Installation

Tested with Inkscape 1.4.4 on Ubuntu 24.04. Python 3.12+ required.

## Prerequisites

```bash
# Inkscape itself
sudo add-apt-repository ppa:inkscape.dev/stable
sudo apt update
sudo apt install inkscape

# Build deps for the Python extensions pulled in by inkex / pygobject
sudo apt install libcairo2-dev libgirepository-2.0-dev libgirepository1.0-dev pkg-config python3-dev

# Clipboard staging for inkscape_live's insert_svg. Either package works on either
# session type — the backend is auto-detected, and on Wayland xclip is used via
# XWayland when wl-clipboard isn't installed.
sudo apt install xclip
# sudo apt install wl-clipboard  # preferred on a native Wayland session
```

You also need **Python 3.12+** and **[uv](https://docs.astral.sh/uv/install/)** (recommended) or any modern pip.

## Install

Three equivalent paths — pick whichever matches your setup.

### A. uvx (recommended for end users)

No clone, no venv to manage; `uvx` fetches `inkscape-mcp` from PyPI on demand and caches it.

```bash
uvx inkscape_mcp --help
```

### B. pip into a venv

```bash
python3 -m venv ~/.venvs/inkscape_mcp
~/.venvs/inkscape_mcp/bin/pip install inkscape-mcp
~/.venvs/inkscape_mcp/bin/inkscape_mcp --help
```

### C. uv into a project

```bash
uv add inkscape-mcp
uv run inkscape_mcp --help
```

> The PyPI distribution is `inkscape-mcp` (hyphen); the Python import name is `inkscape_mcp` (underscore — Python identifiers can't contain hyphens). pip accepts either spelling — it normalizes per PEP 503.

## Register with Claude Code

```bash
claude mcp add inkscape_mcp -s user -- uvx inkscape_mcp
claude mcp list | grep inkscape_mcp   # should show "✓ Connected"
```

The resulting entry in your Claude config:

```json
{
  "mcpServers": {
    "inkscape_mcp": {
      "command": "uvx",
      "args": ["inkscape_mcp"]
    }
  }
}
```

If you installed via venv (option B), point `command` at the venv binary instead:

```json
{
  "command": "/home/you/.venvs/inkscape_mcp/bin/inkscape_mcp"
}
```

## Override the Inkscape binary

To pin a non-default Inkscape build:

```bash
export INKSCAPE_BIN=/opt/inkscape-nightly/bin/inkscape
```

Inspect from the agent with `inkscape_system(operation="diagnostics")` — it reports which value came from which source (env var, config file, default).

## From source (for development)

```bash
git clone https://github.com/aravindev/inkscape_mcp.git ~/git/inkscape_mcp
cd ~/git/inkscape_mcp
uv sync
uv run inkscape_mcp --help
```

Register the dev checkout with Claude Code:

```bash
claude mcp add inkscape_mcp -s user -- uv --directory ~/git/inkscape_mcp run inkscape_mcp
```

## Next

- [INKSCAPE.md](INKSCAPE.md) — Inkscape install details and CLI verification.
- [USAGE.md](USAGE.md) — calling tools.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common build/runtime errors.
