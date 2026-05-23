# Contributing to inkscape_mcp

Local Linux fork. PRs are not currently accepted upstream — see the repo `README.md` for context.

## Dev setup

```bash
sudo apt install inkscape libcairo2-dev libgirepository-2.0-dev libgirepository1.0-dev pkg-config python3-dev
git clone https://github.com/aravindev/inkscape_mcp.git
cd inkscape_mcp
uv sync
```

## Workflow

```bash
uv run pytest -v             # MCP-client-driven test suite
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy src/             # type check
```

Before opening a branch:

- Comments are one-liners that explain _why_. Don't narrate what the code does.
- Add a test under `tests/` whenever you add or change a tool operation.

## License

MIT.
