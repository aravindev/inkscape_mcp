"""Shared setup for the GUI tier.

Everything under `tests/live/` drives a real, running Inkscape over D-Bus. These tests
are excluded from CI (`--ignore=tests/live` in ci.yml) and skip cleanly when no GUI is
reachable, so a local `pytest tests/` stays green either way.

Window hygiene is load-bearing here, not cosmetic:

* `open_file` opens a NEW window on every call, even for a path that is already open.
  Calling it per test therefore leaves one window per test behind — a 17-test run
  produced 35 windows.
* A multi-document session is precisely the state in which `window_id` is ambiguous,
  every live op has to refuse, and auto-save declines to write (it cannot tell which
  window holds the edited document). So a leaked window from an earlier test breaks
  every test after it.

Hence: open the document ONCE per session, reset its contents in place between tests,
and save-then-close it at the end.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import warnings
from pathlib import Path

import pytest

from inkscape_mcp.dbus_client import InkscapeDBus

FIXTURES = Path(__file__).parent.parent / "fixtures"
EXCHANGE = Path(os.path.expanduser("~/.cache/inkscape_mcp/exchange"))

# The document body every test starts from, kept in sync with fixtures/minimal.svg.
_RESET_BODY = (
    '<g inkscape:groupmode="layer" id="layer-base" inkscape:label="base">'
    '<rect id="rect-1" x="10" y="10" width="40" height="40" fill="#cc3333"/>'
    '<circle id="circle-1" cx="100" cy="50" r="20" fill="#3366cc"/>'
    "</g>"
    '<g inkscape:groupmode="layer" id="layer-label" inkscape:label="label">'
    '<text id="text-1" x="140" y="60" font-family="sans-serif" font-size="14" fill="#222">hi</text>'
    "</g>"
)


@pytest.fixture(scope="session", autouse=True)
def _bridge_required():
    if not InkscapeDBus().is_available():
        pytest.skip(
            "Inkscape GUI not running — start it to exercise the live tier",
            allow_module_level=True,
        )


def _active_docname(bus: InkscapeDBus) -> str:
    """Filename of Inkscape's active document, or '' if it can't be determined."""
    result = EXCHANGE / "result.json"
    try:
        result.unlink(missing_ok=True)
        EXCHANGE.mkdir(parents=True, exist_ok=True)
        (EXCHANGE / "input.json").write_text(json.dumps({"category": "view"}))
        bus.activate("org.inkscape.mcp.inspect.noprefs", scope="app")
        for _ in range(60):
            if result.exists() and result.stat().st_size:
                data = json.loads(result.read_text())
                return str((data.get("active_document") or {}).get("docname", ""))
            time.sleep(0.05)
    except Exception:
        return ""
    return ""


@pytest.fixture(scope="session")
def live_session(tmp_path_factory):
    """Open one scratch document for the whole session; save and close it at the end."""
    path = tmp_path_factory.mktemp("live") / "live_doc.svg"
    shutil.copy(FIXTURES / "minimal.svg", path)

    bus = InkscapeDBus()
    before = set(bus.list_windows())
    bus.open_file(str(path))
    for _ in range(40):  # wait for the new window to register on the bus
        if set(bus.list_windows()) - before:
            break
        time.sleep(0.25)

    yield path

    # Closing is only attempted when it can be done SILENTLY. `document-close` prompts
    # "save before closing?" on a dirty document, and that dialog blocks the GUI until
    # a human dismisses it — an unacceptable thing for a test suite to leave behind.
    #
    # A document is dirty here whenever more than one was open, because the MCP's
    # auto-save deliberately declines in that case (it cannot match the edited document
    # to a window). And with several windows open, a window-scoped `document-save`
    # might target someone else's document. So: act only when there is exactly one
    # window and it is demonstrably ours; otherwise leave it and say so.
    try:
        windows = bus.list_windows()
        if len(windows) == 1 and _active_docname(bus) == path.name:
            bus.activate("document-save", scope="window", window_id=windows[0])
            time.sleep(0.5)
            bus.activate("document-close", scope="window", window_id=windows[0])
        elif len(windows) > 1:
            # A warning rather than a print: pytest swallows stdout under -q, and a
            # silently-leaked window is what breaks the *next* run.
            warnings.warn(
                f"live teardown left {len(windows)} Inkscape window(s) open. With more than one "
                "document open the MCP declines to auto-save, so closing would raise a save "
                "dialog. Close them by hand, or run this tier against a single-document session.",
                stacklevel=1,
            )
    except Exception:  # noqa: S110 — teardown is best-effort; a stuck window must not fail the run
        pass


@pytest.fixture
async def live_doc(mcp, live_session: Path) -> Path:
    """Reset the session document to a known state, without opening a window.

    Replacing the body through `edit_xml` rather than reopening the file is what keeps
    this to a single window: `open_file` would spawn a fresh one every time.
    """
    # Only the drawable top-level content is cleared. <defs> and <sodipodi:namedview>
    # are left alone: namedview carries the canvas/view state Inkscape relies on, and
    # removing it mid-session destabilises the GUI.
    existing = await mcp.call_tool(
        "inkscape_live",
        {
            "operation": "execute_inkex",
            "payload": (
                "keep = {'defs', 'namedview', 'metadata'}\n"
                "out = []\n"
                "for c in svg:\n"
                "    tag = c.tag.split('}')[-1]\n"
                "    if tag not in keep and c.get('id'):\n"
                "        out.append(c.get('id'))\n"
                "set_result(out)"
            ),
        },
    )
    ids = (existing.structured_content or {}).get("data", {}).get("result") or []
    for elem_id in ids:
        await mcp.call_tool(
            "inkscape_live",
            {"operation": "edit_xml", "target": f'//*[@id="{elem_id}"]', "payload": '{"action":"remove"}'},
        )
    await mcp.call_tool(
        "inkscape_live",
        {
            "operation": "edit_xml",
            "target": "/svg:svg",
            "payload": json.dumps({"action": "append", "xml": _RESET_BODY}),
        },
    )
    return live_session
