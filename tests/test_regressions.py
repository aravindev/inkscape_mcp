"""Regressions for the silent-success defects fixed on the defect-backlog branch.

Every test here fails on the code as it stood at v1.1.3. The common thread is that
the old behaviour reported ``success: True`` while doing nothing (or the wrong
thing), which is precisely what the pre-existing suite could not see — several of
its assertions were written loosely enough to pass either way.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest
from lxml import etree

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.dbus_client import coerce_bool
from inkscape_mcp.tools.gradient import inkscape_gradient
from inkscape_mcp.tools.vector_operations import _count_path_nodes
from tests._helpers import payload as _payload

SVG = "{http://www.w3.org/2000/svg}"
FIXTURES = Path(__file__).parent / "fixtures"


def _paths(path: Path) -> list[str]:
    root = etree.parse(str(path)).getroot()
    return [e.get("id") or "" for e in root.iter(f"{SVG}path")]


def _gradient(path: Path, gid: str):
    root = etree.parse(str(path)).getroot()
    for tag in ("linearGradient", "radialGradient"):
        for el in root.iter(f"{SVG}{tag}"):
            if el.get("id") == gid:
                return el
    raise AssertionError(f"gradient {gid!r} not found in {path}")


@pytest.fixture
def gradient_pair_svg(tmp_path: Path) -> Path:
    """Inkscape-style gradient pair: stops in one element, geometry in the href-ing one."""
    dest = tmp_path / "inkscape_gradient.svg"
    shutil.copy(FIXTURES / "inkscape_gradient.svg", dest)
    return dest


# --------------------------------------------------------------------------------------
# A1/A2 — action chain construction
# --------------------------------------------------------------------------------------


async def test_execute_actions_rejects_a_string_of_actions(server):
    """A bare string would be ';'.join()ed character-by-character.

    Inkscape then skips every one-character "action", exits 0 anyway, and the export
    comes out unmodified — reported as success. Callers pass cli_wrapper as Any, so
    only a runtime guard can catch this.
    """
    with pytest.raises(TypeError, match="list of action strings"):
        await server.cli_wrapper._execute_actions(
            input_path=str(FIXTURES / "minimal.svg"),
            actions="select-all;path-union",
            output_path="/tmp/never-written.svg",
        )


async def test_export_do_lands_in_actions_not_the_filename(monkeypatch, server, tmp_path):
    """`;export-do` was appended to --export-filename, producing 'Unknown export type'."""
    captured: dict[str, list[str]] = {}

    async def fake_exec(cmd_args, timeout):
        captured["argv"] = cmd_args
        Path(str(tmp_path / "out.svg")).write_text("<svg/>")
        return ""

    monkeypatch.setattr(server.cli_wrapper, "_execute_command", fake_exec)
    await server.cli_wrapper._execute_actions(
        input_path=str(FIXTURES / "minimal.svg"),
        actions=["select-all"],
        output_path=str(tmp_path / "out.svg"),
    )

    argv = captured["argv"]
    actions_arg = next(a for a in argv if a.startswith("--actions="))
    filename_arg = next(a for a in argv if a.startswith("--export-filename="))
    assert actions_arg.endswith(";export-do"), actions_arg
    assert "export-do" not in filename_arg, filename_arg


# --------------------------------------------------------------------------------------
# Action names + selection scope (silently no-oped every affected operation)
# --------------------------------------------------------------------------------------


async def test_apply_boolean_actually_merges_paths(mcp, multi_path_svg, tmp_path):
    """Two overlapping paths must become one.

    Previously broken twice over: the actions were splatted into characters, and
    `selection-union` doesn't exist in Inkscape 1.4 (it's `path-union`).
    """
    out = tmp_path / "union.svg"
    assert len(_paths(multi_path_svg)) == 2

    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "apply_boolean",
            "operation_type": "union",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "select_all": True,
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert len(_paths(out)) == 1, f"union left {_paths(out)} — the boolean did not run"


@pytest.mark.parametrize("operation,target", [("object_raise", "path-a"), ("object_lower", "path-b")])
async def test_object_z_order_actually_changes(mcp, multi_path_svg, tmp_path, operation, target):
    """Raise/lower rewrote nothing and still reported success."""
    out = tmp_path / f"{operation}.svg"
    assert _paths(multi_path_svg) == ["path-a", "path-b"]

    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": operation,
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "object_id": target,
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    # Either raising path-a or lowering path-b must swap the document order.
    assert _paths(out) == ["path-b", "path-a"], f"z-order unchanged: {_paths(out)}"


async def test_path_inset_outset_changes_geometry(mcp, multi_path_svg, tmp_path):
    """`path-outset` doesn't exist in 1.4; the action is `transform-grow:<n>`."""
    out = tmp_path / "outset.svg"
    before = etree.parse(str(multi_path_svg)).getroot()
    before_d = [e.get("d") for e in before.iter(f"{SVG}path")]

    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "path_inset_outset",
            "input_path": str(multi_path_svg),
            "output_path": str(out),
            "offset": 20,
        },
    )
    assert _payload(res)["success"] is True
    after_d = [e.get("d") for e in etree.parse(str(out)).getroot().iter(f"{SVG}path")]
    assert after_d != before_d, "outset produced identical geometry"


async def test_select_all_does_not_target_the_layer_group(mcp, minimal_svg, tmp_path):
    """`select-all:all` selects groups AND layers, so per-object ops hit the layer <g>
    and no-oped. The bare `select-all` (no-groups) is what these operations want."""
    out = tmp_path / "objpath.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "object_to_path", "input_path": str(minimal_svg), "output_path": str(out)},
    )
    assert _payload(res)["success"] is True
    root = etree.parse(str(out)).getroot()
    # rect-1 and circle-1 should now be paths; with the layer selected nothing converted.
    assert len(list(root.iter(f"{SVG}path"))) >= 2, etree.tostring(root, encoding="unicode")[:400]


# --------------------------------------------------------------------------------------
# Previously undispatched / fabricated operations
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["optimize_svg", "scour_svg", "path_break_apart"])
async def test_previously_undispatched_operations_run(mcp, minimal_svg, tmp_path, operation):
    """These were advertised in InkscapeVectorOperation but had no dispatcher branch."""
    out = tmp_path / f"{operation}.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": operation, "input_path": str(minimal_svg), "output_path": str(out)},
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert p.get("error") != "NotImplementedError"
    assert out.exists() and out.stat().st_size > 0


async def test_scour_strips_editor_state(mcp, minimal_svg, tmp_path):
    out = tmp_path / "scoured.svg"
    assert "inkscape:" in minimal_svg.read_text()
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "scour_svg", "input_path": str(minimal_svg), "output_path": str(out)},
    )
    assert _payload(res)["success"] is True
    assert "inkscape:" not in out.read_text()


async def test_layers_to_files_writes_one_file_per_layer(mcp, minimal_svg, tmp_path):
    out_dir = tmp_path / "layers"
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "layers_to_files", "input_path": str(minimal_svg), "output_dir": str(out_dir)},
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert sorted(f.name for f in out_dir.glob("*.png")) == ["base.png", "label.png"]


async def test_count_nodes_counts_real_nodes(mcp, multi_path_svg):
    """Used to return a hardcoded 42."""
    res = await mcp.call_tool("inkscape_vector", {"operation": "count_nodes", "input_path": str(multi_path_svg)})
    p = _payload(res)
    assert p["success"] is True, p
    # Each fixture path is M + 3 L + Z = 4 nodes.
    assert p["data"]["node_count"] == 8, p["data"]
    assert p["data"]["paths"] == {"path-a": 4, "path-b": 4}


@pytest.mark.parametrize(
    "d,expected",
    [
        ("M 0 0 L 10 0 L 10 10 Z", 3),
        ("M 0 0 L 1 1 2 2 3 3", 4),  # implicit repeated command
        ("M 0 0 C 1 1 2 2 3 3", 2),
        ("M 0 0 H 5 V 5 Z", 3),
        ("", 0),
    ],
)
def test_count_path_nodes_handles_implicit_commands(d, expected):
    assert _count_path_nodes(d) == expected


async def test_query_document_reports_real_counts(mcp, minimal_svg):
    """num_objects/num_layers were hardcoded to 1."""
    res = await mcp.call_tool("inkscape_vector", {"operation": "query_document", "input_path": str(minimal_svg)})
    p = _payload(res)
    assert p["success"] is True, p
    assert p["data"]["num_objects"] == 3  # rect + circle + text
    assert p["data"]["num_layers"] == 2


async def test_statistics_is_not_the_placeholder_branch(mcp, minimal_svg):
    """A duplicate `if operation == "statistics"` shadowed the real implementation."""
    res = await mcp.call_tool("inkscape_analysis", {"operation": "statistics", "input_path": str(minimal_svg)})
    p = _payload(res)
    assert p["success"] is True, p
    assert p["data"]["shape_count"] == 3
    assert p["data"]["layer_count"] == 2
    assert "num_objects" not in p["data"], "still returning the hardcoded placeholder payload"


async def test_set_document_units_rewrites_the_document(mcp, minimal_svg, tmp_path):
    """Used to change nothing and report success."""
    out = tmp_path / "mm.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "set_document_units",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "units": "mm",
        },
    )
    assert _payload(res)["success"] is True
    root = etree.parse(str(out)).getroot()
    assert root.get("width") == "200mm"
    assert root.get("height") == "100mm"
    # viewBox must survive, or the geometry silently rescales.
    assert root.get("viewBox") == "0 0 200 100"


async def test_set_document_units_rejects_unknown_units(mcp, minimal_svg, tmp_path):
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "set_document_units",
            "input_path": str(minimal_svg),
            "output_path": str(tmp_path / "bad.svg"),
            "units": "furlongs",
        },
    )
    assert _payload(res)["success"] is False


async def test_generate_barcode_qr_emits_a_real_qr(mcp, tmp_path):
    """Used to write the payload into a <text> element — a label, not a code — and
    interpolated it into XML unescaped, so any & produced an unparseable file."""
    out = tmp_path / "qr.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "generate_barcode_qr",
            "output_path": str(out),
            "barcode_data": "https://example.com/?a=1&b=2",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    root = etree.parse(str(out)).getroot()  # must parse: & would have broken it
    assert not list(root.iter(f"{SVG}text")), "still writing a text label instead of a QR"
    d = "".join((e.get("d") or "") for e in root.iter(f"{SVG}path"))
    assert len(d) > 1000, "QR path suspiciously small"


async def test_generate_barcode_qr_requires_data(mcp, tmp_path):
    res = await mcp.call_tool(
        "inkscape_vector",
        {"operation": "generate_barcode_qr", "output_path": str(tmp_path / "qr.svg")},
    )
    assert _payload(res)["success"] is False


# --------------------------------------------------------------------------------------
# A5/A6 — gradient href inheritance and gradientUnits
# --------------------------------------------------------------------------------------


async def test_list_stops_follows_xlink_href(server, gradient_pair_svg):
    """Asking about the id that appears in fill=url(#…) returned 'found 0 stops'."""
    res = await inkscape_gradient(
        operation="list_stops",
        input_path=str(gradient_pair_svg),
        output_path="",
        gradient_id="applied-ramp",
        cli_wrapper=server.cli_wrapper,
        config=server.config,
    )
    assert res["success"] is True, res
    assert len(res["data"]["stops"]) == 2, res["data"]
    assert res["data"]["inherited_via_href"] is True
    assert res["data"]["stops_from"] == "stops-ramp"


async def test_add_stop_preserves_href_inheritance(server, gradient_pair_svg, tmp_path):
    """Writing a stop into the referencing gradient stops inheritance per SVG 1.1,
    collapsing a two-stop ramp to a flat colour."""
    out = tmp_path / "added.svg"
    res = await inkscape_gradient(
        operation="add_stop",
        input_path=str(gradient_pair_svg),
        output_path=str(out),
        gradient_id="applied-ramp",
        stop_offset="50%",
        stop_color="#00ff00",
        cli_wrapper=server.cli_wrapper,
        config=server.config,
    )
    assert res["success"] is True, res
    assert res["data"]["modified_gradient"] == "stops-ramp"

    holder = _gradient(out, "stops-ramp")
    applied = _gradient(out, "applied-ramp")
    assert len(list(holder.iter(f"{SVG}stop"))) == 3, "new stop did not land on the stop holder"
    assert len(list(applied.iter(f"{SVG}stop"))) == 0, "stop written onto the href-ing gradient breaks inheritance"


async def test_convert_to_radial_respects_user_space_units(server, gradient_pair_svg, tmp_path):
    """cx/cy/r of 0.5 are objectBoundingBox fractions; under userSpaceOnUse they put a
    half-pixel gradient at the document origin."""
    out = tmp_path / "radial.svg"
    res = await inkscape_gradient(
        operation="convert_to_radial",
        input_path=str(gradient_pair_svg),
        output_path=str(out),
        gradient_id="applied-ramp",
        cli_wrapper=server.cli_wrapper,
        config=server.config,
    )
    assert res["success"] is True, res

    grad = _gradient(out, "applied-ramp")
    assert grad.get("gradientUnits") == "userSpaceOnUse"
    # x1=20..x2=180 at y=100 -> centre (100,100), radius 80.
    assert float(grad.get("cx")) == pytest.approx(100)
    assert float(grad.get("cy")) == pytest.approx(100)
    assert float(grad.get("r")) == pytest.approx(80)


async def test_convert_to_linear_respects_user_space_units(server, gradient_pair_svg, tmp_path):
    out = tmp_path / "linear.svg"
    res = await inkscape_gradient(
        operation="convert_to_linear",
        input_path=str(gradient_pair_svg),
        output_path=str(out),
        gradient_id="applied-radial",
        cli_wrapper=server.cli_wrapper,
        config=server.config,
    )
    assert res["success"] is True, res

    grad = _gradient(out, "applied-radial")
    # cx=100 cy=100 r=80 -> a horizontal line across the diameter.
    assert float(grad.get("x1")) == pytest.approx(20)
    assert float(grad.get("x2")) == pytest.approx(180)
    assert float(grad.get("y1")) == pytest.approx(100)


# --------------------------------------------------------------------------------------
# A9 — boolean coercion for D-Bus action parameters
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("false", False),
        ("False", False),
        (" off ", False),
        ("no", False),
        ("0", False),
        ("", False),
        ("true", True),
        ("1", True),
        ("yes", True),
        (True, True),
        (False, False),
    ],
)
def test_coerce_bool_handles_textual_falsey_values(value, expected):
    """bool('false') is True, so no b-signature action could ever be turned off —
    asking to disable export-overwrite enabled it."""
    assert coerce_bool(value) is expected


# --------------------------------------------------------------------------------------
# B1/B5 — MCP surface and CLI startup
# --------------------------------------------------------------------------------------


async def test_tool_schemas_expose_the_parameters_operations_need(mcp):
    """The wrappers exposed 3-4 params while the implementations needed 20+, making
    several advertised operations impossible to satisfy over MCP."""
    tools = {t.name: set((t.inputSchema or {}).get("properties", {})) for t in await mcp.list_tools()}

    assert {"object_ids", "select_all", "operation_type", "source_id", "barcode_data"} <= tools["inkscape_vector"]
    assert {"input_paths", "output_dir", "quality"} <= tools["inkscape_file"]
    assert {"extension_id", "input_file"} <= tools["inkscape_system"]


async def test_batch_convert_is_satisfiable_over_mcp(mcp, minimal_svg, tmp_path):
    """input_paths/output_dir weren't on the wrapper, so this always failed validation."""
    out_dir = tmp_path / "batch"
    res = await mcp.call_tool(
        "inkscape_file",
        {
            "operation": "batch_convert",
            "input_paths": [str(minimal_svg)],
            "output_dir": str(out_dir),
            "format": "png",
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert (out_dir / "minimal.png").exists()


async def test_tile_clone_is_satisfiable_over_mcp(mcp, minimal_svg, tmp_path):
    out = tmp_path / "tiled.svg"
    res = await mcp.call_tool(
        "inkscape_vector",
        {
            "operation": "tile_clone",
            "input_path": str(minimal_svg),
            "output_path": str(out),
            "source_id": "rect-1",
            "rows": 2,
            "cols": 3,
        },
    )
    p = _payload(res)
    assert p["success"] is True, p
    assert p["data"]["clones_created"] == 6


def test_transport_accepts_the_cli_flags_main_defines():
    """main parsed --mode/--log-level, then transport re-parsed sys.argv with a
    different parser and aborted with 'unrecognized arguments' after a full init."""
    from inkscape_mcp.transport import resolve_config

    # Inert namespace data, not an actual bind.
    args = argparse.Namespace(
        stdio=False,
        http=True,
        sse=False,
        host="0.0.0.0",  # noqa: S104
        port=9999,
        path=None,
        debug=False,
    )
    cfg = resolve_config(args)
    assert cfg["transport"] == "http"
    assert cfg["host"] == "0.0.0.0"  # noqa: S104
    assert cfg["port"] == 9999


def test_server_reads_config_without_an_explicit_config_flag(monkeypatch, tmp_path):
    """The config file and every env override were dead unless --config was passed."""
    from inkscape_mcp.config import load_config

    monkeypatch.setenv("INKSCAPE_MCP_TIMEOUT", "45")
    assert load_config().process_timeout == 45


def test_invalid_timeout_env_does_not_kill_startup(monkeypatch):
    """A non-numeric value raised an uncaught ValueError; an out-of-range one was
    silently accepted because assignment bypassed pydantic validation."""
    from inkscape_mcp.config import load_config

    monkeypatch.setenv("INKSCAPE_MCP_TIMEOUT", "not-a-number")
    assert load_config().process_timeout == 30

    monkeypatch.setenv("INKSCAPE_MCP_TIMEOUT", "999")  # exceeds le=300
    assert load_config().process_timeout == 30


# --------------------------------------------------------------------------------------
# A10 — timings
# --------------------------------------------------------------------------------------


async def test_execution_time_is_measured(mcp, minimal_svg):
    """13 sites computed (time.time() - time.time()), so every timing was 0."""
    res = await mcp.call_tool("inkscape_vector", {"operation": "query_document", "input_path": str(minimal_svg)})
    p = _payload(res)
    assert p["success"] is True
    assert p["execution_time_ms"] > 0, "timing still reports zero"


# --------------------------------------------------------------------------------------
# B6 — packaged reference docs
# --------------------------------------------------------------------------------------


def test_reference_docs_are_importable_package_data():
    """These were resolved relative to the repo root, so every resource://inkscape/*
    doc returned 'not found' from a wheel install."""
    from importlib import resources

    for name in ("mcp-workflow.md", "inkscape-1.4.4-actions.txt", "inkscape-1.4.4-help.txt"):
        assert (resources.files("inkscape_mcp.reference") / name).read_text(encoding="utf-8")


async def test_doc_resources_resolve(mcp):
    contents = await mcp.read_resource("resource://inkscape/mcp-workflow")
    text = contents[0].text
    assert "not found" not in text[:200]
    assert len(text) > 1000


# --------------------------------------------------------------------------------------
# B7/E5 — system tool
# --------------------------------------------------------------------------------------


async def test_list_extensions_reports_real_extensions(mcp):
    """Returned 'Extension system disabled - plugins directory removed' while the
    inkscape_extension tool discovered them perfectly well."""
    res = await mcp.call_tool("inkscape_system", {"operation": "list_extensions"})
    p = _payload(res)
    assert p["success"] is True, p
    assert p["data"]["total_count"] > 0, "still reporting the extension system as disabled"


async def test_execute_extension_requires_but_accepts_parameters(mcp):
    res = await mcp.call_tool("inkscape_system", {"operation": "execute_extension"})
    p = _payload(res)
    assert p["success"] is False
    # Used to surface as a pydantic ValidationError about the missing `data` field.
    assert "Extension ID is required" in p["message"], p["message"]


async def test_version_is_not_hardcoded(mcp):
    from inkscape_mcp import __version__

    res = await mcp.call_tool("inkscape_system", {"operation": "version"})
    assert __version__ in _payload(res)["data"]["server"]

    res = await mcp.call_tool("inkscape_system", {"operation": "status"})
    assert _payload(res)["data"]["server"]["version"] == __version__


# --------------------------------------------------------------------------------------
# Plugin argument handling
# --------------------------------------------------------------------------------------


def test_plugin_booleans_round_trip_false(minimal_svg):
    """argparse type=bool made every plugin boolean permanently True, because
    bool('false') is True. Inkscape passes booleans as the literal strings."""
    import importlib.util

    for module_name, flag in (
        ("ag_unity_prep", "flatten_groups"),
        ("ag_color_quantize", "dither"),
        ("ag_layer_animation", "loop"),
        ("ag_batch_trace", "simplify"),
    ):
        path = Path("src/inkscape_mcp/plugins") / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = next(
            obj
            for name, obj in vars(module).items()
            if isinstance(obj, type) and name.startswith("AG") and name != "AG"
        )
        parser = cls().arg_parser
        assert getattr(parser.parse_args([f"--{flag}=false", str(minimal_svg)]), flag) is False, module_name
        assert getattr(parser.parse_args([f"--{flag}=true", str(minimal_svg)]), flag) is True, module_name


def test_flattening_preserves_absolute_position(tmp_path):
    """Re-parenting children without composing the group transform moved everything
    back to the origin — including layer transforms, since Layer subclasses Group."""
    import subprocess
    import sys

    src = tmp_path / "grouped.svg"
    src.write_text(
        '<?xml version="1.0"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500">'
        '<g id="outer" transform="translate(300,200)">'
        '<g id="inner" transform="scale(2)" style="fill:#ff0000">'
        '<path id="p1" d="M 0 0 L 10 0 L 10 10 Z"/>'
        "</g></g></svg>\n"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "src/inkscape_mcp/plugins/ag_unity_prep.py",
            "--flatten_groups=true",
            "--reset_coordinates=false",
            "--optimize_paths=false",
            "--remove_metadata=false",
            str(src),
        ],
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    root = etree.fromstring(proc.stdout)
    p1 = next(e for e in root.iter() if e.get("id") == "p1")
    assert not list(root.iter(f"{SVG}g")), "groups were not flattened"
    # translate(300,200) @ scale(2) == matrix(2 0 0 2 300 200)
    transform = (p1.get("transform") or "").replace(" ", "")
    assert "2" in transform and "300" in transform and "200" in transform, p1.get("transform")
    assert "fill:#ff0000" in (p1.get("style") or ""), "group style was not merged down"


def test_flattening_leaves_clipped_groups_alone(tmp_path):
    """A clip-path applies to the group as a unit; dissolving it changes rendering."""
    import subprocess
    import sys

    src = tmp_path / "clipped.svg"
    src.write_text(
        '<?xml version="1.0"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<g id="clipped" clip-path="url(#c1)"><path id="p2" d="M 5 5 L 6 6"/></g>'
        "</svg>\n"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "src/inkscape_mcp/plugins/ag_unity_prep.py",
            "--flatten_groups=true",
            "--reset_coordinates=false",
            "--optimize_paths=false",
            "--remove_metadata=false",
            str(src),
        ],
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    assert b"cannot flatten safely" in proc.stderr


# --------------------------------------------------------------------------------------
# E6 — tile_clone document preservation
# --------------------------------------------------------------------------------------


def test_tile_clone_preserves_comments_and_pis(tmp_path):
    """Rebuilding the root to add the xlink prefix dropped everything outside it."""
    from inkscape_mcp.tools.tile_clone import tile_clone

    src = tmp_path / "in.svg"
    src.write_text(
        '<?xml version="1.0"?>\n<!-- leading comment -->\n<?some-pi data?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<!-- inner comment --><rect id="r" width="10" height="10"/></svg>\n'
    )
    out = tmp_path / "out.svg"
    res = tile_clone(input_path=str(src), output_path=str(out), source_id="r", rows=2, cols=2)

    assert res["success"] is True, res
    text = out.read_text()
    assert "leading comment" in text
    assert "some-pi" in text
    assert "inner comment" in text
    assert "xmlns:xlink" in text


def test_cli_wrapper_construction_requires_a_real_executable(tmp_path):
    with pytest.raises(Exception, match=r"not found|not configured"):
        InkscapeCliWrapper(argparse.Namespace(inkscape_executable=str(tmp_path / "nope"), process_timeout=30))
