"""Shared SVG write helper used by lxml-mutating tools."""

from __future__ import annotations

from pathlib import Path

from lxml import etree


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
