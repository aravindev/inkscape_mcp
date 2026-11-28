"""gdbus client routing (Windows/macOS live bridge), with gdbus itself mocked.

Window scope uses ``/window/N`` when Inkscape exports window objects and falls back to
``/document/N`` when it does not; document scope always uses ``/document/N``.
"""

from __future__ import annotations

import pytest

from inkscape_mcp.win_dbus_client import GDBusError, GDBusInkscapeDBus

APP = "/org/inkscape/Inkscape"
WINDOW = f"{APP}/window"
DOCUMENT = f"{APP}/document"


def _client(monkeypatch, tree: dict[str, str]):
    """A client whose gdbus answers introspection from ``tree`` and records calls."""
    calls: list[tuple[str, str]] = []

    def run(args):
        path = args[args.index("--object-path") + 1]
        if args[0] == "introspect":
            calls.append((path, "Introspect"))
            if path not in tree:
                raise GDBusError(f"No such object path '{path}'")
            return tree[path]
        method = args[args.index("--method") + 1]
        calls.append((path, method))
        if method.endswith("Describe"):
            return "((true, signature '', @av []),)"
        if method.endswith("List"):
            return "(['undo'],)"
        return "()"

    client = GDBusInkscapeDBus("gdbus", "unix:path=/tmp/test-bus")
    monkeypatch.setattr(client, "_run", run)
    return client, calls


LINUX_LIKE = {
    WINDOW: "node /org/inkscape/Inkscape/window {\n  node 3 {\n  };\n};",
    DOCUMENT: "node /org/inkscape/Inkscape/document {\n  node 5 {\n  };\n};",
}
NO_WINDOWS = {
    WINDOW: "node /org/inkscape/Inkscape/window {\n};",
    DOCUMENT: "node /org/inkscape/Inkscape/document {\n  node 5 {\n  };\n};",
}


def test_window_scope_uses_window_objects_when_exported(monkeypatch):
    client, calls = _client(monkeypatch, LINUX_LIKE)
    client.activate("document-save", scope="window", window_id=3)
    assert calls[-1] == (f"{WINDOW}/3", "org.gtk.Actions.Activate")
    assert client.list_windows() == [3]


@pytest.mark.parametrize("tree", [NO_WINDOWS, {DOCUMENT: NO_WINDOWS[DOCUMENT]}])
def test_window_scope_falls_back_to_document_objects(monkeypatch, tree):
    client, calls = _client(monkeypatch, tree)
    client.activate("select-all", scope="window", window_id=5)
    assert calls[-1] == (f"{DOCUMENT}/5", "org.gtk.Actions.Activate")
    assert client.list_windows() == [5]


@pytest.mark.parametrize("tree", [LINUX_LIKE, NO_WINDOWS])
def test_document_scope_always_uses_document_objects(monkeypatch, tree):
    client, calls = _client(monkeypatch, tree)
    assert client.list_actions(scope="document", window_id=5) == ["undo"]
    assert calls == [(f"{DOCUMENT}/5", "org.gtk.Actions.List")]
    assert client.list_documents() == [5]


def test_window_probe_runs_once_per_client(monkeypatch):
    client, calls = _client(monkeypatch, LINUX_LIKE)
    client.list_actions(scope="window", window_id=3)
    client.list_actions(scope="window", window_id=3)
    assert calls.count((WINDOW, "Introspect")) == 1


def test_app_scope_never_probes(monkeypatch):
    client, calls = _client(monkeypatch, LINUX_LIKE)
    client.list_actions(scope="app")
    assert calls == [(APP, "org.gtk.Actions.List")]
