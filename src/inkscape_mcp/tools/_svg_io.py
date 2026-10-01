"""Shared SVG read/write helpers used by lxml-mutating tools."""

from __future__ import annotations

from pathlib import Path

from lxml import etree


def safe_parser(**kwargs: bool) -> etree.XMLParser:
    """An XML parser that never resolves entities, loads DTDs or touches the network.

    SVGs come from untrusted sources. lxml's recent defaults already refuse external entities,
    but that is a version-dependent default; this makes it explicit. Extra keyword arguments
    (e.g. ``remove_blank_text``) pass through to ``XMLParser``.
    """
    opts: dict[str, bool] = {"resolve_entities": False, "no_network": True, "load_dtd": False, "huge_tree": False}
    opts.update(kwargs)
    return etree.XMLParser(**opts)


def parse_svg(path: str) -> etree._ElementTree:
    """Parse an SVG file with :func:`safe_parser`."""
    return etree.parse(path, safe_parser(remove_blank_text=False))


def write_tree(
    tree: etree._ElementTree,
    output_path: str,
    *,
    xml_declaration: bool = True,
    encoding: str = "UTF-8",
    standalone: bool = False,
) -> None:
    """Persist `tree` to `output_path`, creating parent dirs as needed."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        output_path,
        xml_declaration=xml_declaration,
        encoding=encoding,
        standalone=standalone,
    )
