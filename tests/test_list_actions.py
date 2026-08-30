"""Unit tests for the enhanced list_actions op — annotation + filter.

The op shells out to ``inkscape --action-list`` (memoised) to build a
name→description map, then annotates the D-Bus action lists and applies an
optional substring filter. We mock both the bus and the subprocess call.
"""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock

import pytest

from inkscape_mcp.tools import live

_FAKE_ACTION_LIST_OUTPUT = """about               :  Inkscape version, authors, license
layer-new           :  Create a new layer above the current
layer-new-above     :  Create a new layer above the current one
layer-delete        :  Delete the current layer
select-by-id        :  Select objects by id
snap-grid           :  Enable snapping to grid points
transform-translate :  Move the selection by an offset
com.kaioa.lorem-ipsum:  Lorem Ipsum
"""


@pytest.fixture(autouse=True)
def reset_action_cache():
    """Clear the module-level cache so each test starts clean."""
    live._ACTION_DESCRIPTIONS = None
    yield
    live._ACTION_DESCRIPTIONS = None


@pytest.fixture
def mock_action_list(monkeypatch):
    """Pretend `inkscape --action-list` returns our canned output."""

    def fake_run(argv, **kwargs):
        completed = MagicMock()
        completed.stdout = _FAKE_ACTION_LIST_OUTPUT
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)


def _make_bus(app_actions: list[str], window_actions: list[str]):
    """Build a MagicMock bus whose list_actions returns our canned lists."""
    bus = MagicMock()

    def list_actions(scope, *args):
        return app_actions if scope == "app" else window_actions

    bus.list_actions.side_effect = list_actions
    return bus


def test_load_action_descriptions_parses_format(mock_action_list):
    descs = live._load_action_descriptions()
    assert descs["layer-new"] == "Create a new layer above the current"
    assert descs["snap-grid"] == "Enable snapping to grid points"
    # The Lorem Ipsum extension has its full id as the action name.
    assert descs["com.kaioa.lorem-ipsum"] == "Lorem Ipsum"


def test_load_action_descriptions_returns_empty_when_inkscape_missing(monkeypatch):
    def fake_run(*a, **kw):
        raise FileNotFoundError("no inkscape on PATH")

    monkeypatch.setattr(subprocess, "run", fake_run)
    descs = live._load_action_descriptions()
    assert descs == {}


def test_load_action_descriptions_returns_empty_on_timeout(monkeypatch):
    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    descs = live._load_action_descriptions()
    assert descs == {}


def test_load_action_descriptions_is_cached(monkeypatch):
    """Second call must NOT re-shell to inkscape."""
    calls = {"n": 0}

    def fake_run(*a, **kw):
        calls["n"] += 1
        completed = MagicMock()
        completed.stdout = "abc :  hi\n"
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)
    live._load_action_descriptions()
    live._load_action_descriptions()
    live._load_action_descriptions()
    assert calls["n"] == 1


async def test_list_actions_annotates_each_entry(mock_action_list):
    bus = _make_bus(["layer-new", "select-by-id"], ["snap-grid"])
    res = await live._op_list_actions(bus, "list_actions", 1, "", time.perf_counter())
    assert res["success"] is True
    by_name = {a["name"]: a["description"] for a in res["data"]["app"]}
    assert by_name["layer-new"] == "Create a new layer above the current"
    assert by_name["select-by-id"] == "Select objects by id"
    win_desc = res["data"]["window"][0]
    assert win_desc == {"name": "snap-grid", "description": "Enable snapping to grid points"}


async def test_list_actions_noprefs_variant_falls_back_to_base_description(mock_action_list):
    bus = _make_bus(["com.kaioa.lorem-ipsum", "com.kaioa.lorem-ipsum.noprefs"], [])
    res = await live._op_list_actions(bus, "list_actions", 1, "", time.perf_counter())
    by_name = {a["name"]: a["description"] for a in res["data"]["app"]}
    assert by_name["com.kaioa.lorem-ipsum"] == "Lorem Ipsum"
    # .noprefs variant — same description as base.
    assert by_name["com.kaioa.lorem-ipsum.noprefs"] == "Lorem Ipsum"


async def test_list_actions_filter_matches_name(mock_action_list):
    bus = _make_bus(
        ["layer-new", "layer-new-above", "layer-delete", "select-by-id"],
        ["snap-grid"],
    )
    res = await live._op_list_actions(bus, "list_actions", 1, "layer-new", time.perf_counter())
    names = {a["name"] for a in res["data"]["app"]}
    assert names == {"layer-new", "layer-new-above"}
    assert res["data"]["window"] == []
    assert res["data"]["filter"] == "layer-new"
    assert "matching" in res["message"]


async def test_list_actions_filter_matches_description(mock_action_list):
    bus = _make_bus(["layer-new", "snap-grid", "transform-translate"], [])
    res = await live._op_list_actions(bus, "list_actions", 1, "snap", time.perf_counter())
    # "snap-grid" matches by name AND description; nothing else.
    names = {a["name"] for a in res["data"]["app"]}
    assert names == {"snap-grid"}


async def test_list_actions_filter_is_case_insensitive(mock_action_list):
    bus = _make_bus(["layer-new", "select-by-id"], [])
    res = await live._op_list_actions(bus, "list_actions", 1, "LAYER", time.perf_counter())
    names = {a["name"] for a in res["data"]["app"]}
    assert names == {"layer-new"}


async def test_list_actions_unannotated_when_inkscape_unavailable(monkeypatch):
    """If --action-list can't be parsed, the op still works — descriptions are empty."""

    def fake_run(*a, **kw):
        raise FileNotFoundError("inkscape missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    bus = _make_bus(["layer-new"], [])
    res = await live._op_list_actions(bus, "list_actions", 1, "", time.perf_counter())
    assert res["success"] is True
    assert res["data"]["app"][0] == {"name": "layer-new", "description": ""}
