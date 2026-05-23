"""Session-wide fixtures: an in-process MCP client backed by the live server."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from fastmcp import Client

from inkscape_mcp.main import InkscapeMCPServer

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run against Inkscape versions outside 1.4.x — the only supported line."""
    binary = shutil.which("inkscape")
    if binary is None:
        pytest.exit("Inkscape not found on $PATH. See docs/INSTALL.md.", returncode=2)
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    match = re.search(r"Inkscape\s+(\d+)\.(\d+)", out.stdout)
    if not match or (int(match.group(1)), int(match.group(2))) != (1, 4):
        pytest.exit(
            f"Unsupported Inkscape version. Expected 1.4.x, got: {out.stdout.strip()}",
            returncode=2,
        )


@pytest_asyncio.fixture(scope="session")
async def server() -> InkscapeMCPServer:
    """Boot the server once per session."""
    s = InkscapeMCPServer()
    ok = await s.initialize()
    assert ok, "Server failed to initialize"
    assert s.cli_wrapper is not None, "CLI wrapper should exist when Inkscape is on PATH"
    return s


@pytest_asyncio.fixture
async def mcp(server: InkscapeMCPServer):
    """A connected MCP Client speaking to the in-process server. Re-opened per test."""
    async with Client(server.mcp) as client:
        yield client


@pytest.fixture
def minimal_svg(tmp_path: Path) -> Path:
    """A small SVG with stable ids — rect, circle, text, two layers."""
    dest = tmp_path / "minimal.svg"
    shutil.copy(FIXTURES / "minimal.svg", dest)
    return dest


@pytest.fixture
def multi_path_svg(tmp_path: Path) -> Path:
    """Two overlapping paths for boolean ops."""
    dest = tmp_path / "multi.svg"
    shutil.copy(FIXTURES / "multi_path.svg", dest)
    return dest


@pytest.fixture
def trace_bitmap(tmp_path: Path) -> Path:
    """A tiny PNG suitable for bitmap tracing."""
    dest = tmp_path / "trace.png"
    shutil.copy(FIXTURES / "bitmap_for_trace.png", dest)
    return dest
