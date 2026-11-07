# Installation

Tested with Inkscape 1.4.4 on Ubuntu 24.04, Windows 11, and macOS (Apple Silicon).
Python 3.12+ required.

## macOS

**Use a source checkout with `uv sync`.** The macOS PyGObject exclusion is a
root-project uv override, not published package metadata. The standalone `uvx`,
pip, and `uv add` instructions below are not currently supported macOS install
paths: inkex's dependencies may still trigger native PyGObject/pycairo builds.

```bash
# Inkscape from inkscape.org, installed as /Applications/Inkscape.app
# Live bridge transport (macOS has no session bus of its own):
brew install dbus glib

# Pin the app-bundle executable (it is not on $PATH):
export INKSCAPE_BIN=/Applications/Inkscape.app/Contents/MacOS/inkscape

# From a source checkout:
uv sync
uv run inkscape_mcp --help

# Use your absolute checkout path when registering the server:
claude mcp add inkscape_mcp -s user -- uv run --directory /absolute/path/to/inkscape_mcp inkscape_mcp
```

The MCP starts a private `dbus-daemon` and launches its own Inkscape under it;
a Finder-launched Inkscape is not reachable from the live bridge. The managed
instance uses `~/.cache/inkscape_mcp/inkscape-profile`, separate from your normal
profile and any `INKSCAPE_PROFILE_DIR` override (which headless tools still honor).
Immediately before launch, only this isolated profile's `python-interpreter` is
set to the MCP Python for bridge plugins. This works around bundled-Python stalls
observed on some installations, not a proven defect in every macOS build. Disable
the workaround with `INKSCAPE_MCP_SET_PYTHON_PREF=0`. Headless initialization and
diagnostics do not change interpreter preferences; diagnostics never start a bus.

System extensions are read from
`/Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions`;
bridge plugins are installed to
`~/.cache/inkscape_mcp/inkscape-profile/extensions/inkscape_mcp`.

## Prerequisites

```bash
# Inkscape itself
sudo add-apt-repository ppa:inkscape.dev/stable
sudo apt update
sudo apt install inkscape

# Build deps for the Python extensions pulled in by inkex / pygobject
sudo apt install libcairo2-dev libgirepository-2.0-dev libgirepository1.0-dev pkg-config python3-dev
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
