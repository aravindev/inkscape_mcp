# Installation

Tested with Inkscape 1.4.4 on Ubuntu 24.04, Windows 11, and macOS (Apple Silicon).
Python 3.12+ required. On Python 3.14 the server does not install `inkex` from PyPI
(its `lxml<6` cap has no 3.14 wheels); extensions use the copy bundled with Inkscape.

## macOS

Install Inkscape 1.4.x from inkscape.org as `/Applications/Inkscape.app` (it is found
there automatically), plus D-Bus and GLib for the live bridge:

```bash
brew install dbus glib
```

**Python 3.14+: `uvx` works.** On 3.14 the server installs no pip `inkex`, so nothing
pulls in PyGObject/pycairo. This needs an inkscape-mcp release newer than 1.3.1.

```bash
uvx --python 3.14 inkscape_mcp --help
claude mcp add inkscape_mcp -s user -- uvx --python 3.14 inkscape_mcp
```

**Python 3.12/3.13: use a source checkout.** There pip `inkex` depends on PyGObject,
which has no macOS wheels. The project's `[tool.uv]` override that skips it applies only
to a checkout, not to `uvx`, pip or `uv add` installs. The checkout's `.python-version`
selects 3.14 anyway.

```bash
uv sync
uv run inkscape_mcp --help

# Use your absolute checkout path when registering the server:
claude mcp add inkscape_mcp -s user -- uv run --directory /absolute/path/to/inkscape_mcp inkscape_mcp
```

### How the live bridge runs on macOS

- The MCP starts a private `dbus-daemon` and launches its own Inkscape under it. A
  Finder-launched Inkscape, or one on a session bus you started yourself (for example
  from a LaunchAgent), is **not reachable**; only the managed instance is. Use
  `inkscape_live` `open_file` to work on a document.
- The managed instance uses `~/.cache/inkscape_mcp/inkscape-profile`, and headless
  CLI runs use `~/.cache/inkscape_mcp/cli-profile`. Your own extensions, preferences
  and templates are **not available** in either. Your normal profile is never changed.
  A headless run honors an `INKSCAPE_PROFILE_DIR` you set; the managed instance does not.
- Both profiles set `python-interpreter` to the MCP's Python, because Inkscape's
  bundled Python stalls or is killed on some installations (it is killed at launch on
  macOS 27 with Inkscape 1.4.4). Disable this with `INKSCAPE_MCP_SET_PYTHON_PREF=0`.
  Headless initialization and diagnostics do not change interpreter preferences, and
  diagnostics never start a bus.
- Extensions that open their own GTK window (those using `inkex.gui`, such as Import
  Web Image) do not run in the managed instance: the MCP's Python has no PyGObject.
- macOS Inkscape has no `document-save` over D-Bus. After a live edit the MCP saves by
  exporting the document over its own file, which works for files it opened (`open_file`
  or at launch). Inkscape still marks the document as modified, so closing the window
  asks to save; the file on disk already matches.

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
