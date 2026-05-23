"""Dublin-Core / RDF document metadata read+write."""

from __future__ import annotations

import time
from typing import Any

from lxml import etree
from pydantic import BaseModel

SVG_NS = "http://www.w3.org/2000/svg"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC_NS = "http://purl.org/dc/elements/1.1/"
CC_NS = "http://creativecommons.org/ns#"

SVG = f"{{{SVG_NS}}}"
RDF = f"{{{RDF_NS}}}"
DC = f"{{{DC_NS}}}"
CC = f"{{{CC_NS}}}"

NSMAP = {"rdf": RDF_NS, "dc": DC_NS, "cc": CC_NS}


class MetadataResult(BaseModel):
    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


def _ensure_child(parent: etree._Element, tag: str, nsmap: dict[str, str] | None = None) -> etree._Element:
    """Find or create the named child, preserving order on creation."""
    child = parent.find(tag)
    if child is None:
        child = etree.SubElement(parent, tag, nsmap=nsmap) if nsmap else etree.SubElement(parent, tag)
    return child


def _ensure_scaffold(root: etree._Element) -> etree._Element:
    """Return <cc:Work>, creating <metadata>/<rdf:RDF>/<cc:Work> as needed."""
    metadata = root.find(f"{SVG}metadata")
    if metadata is None:
        # Put metadata first — Inkscape's own convention.
        metadata = etree.Element(f"{SVG}metadata")
        root.insert(0, metadata)
    rdf = metadata.find(f"{RDF}RDF")
    if rdf is None:
        rdf = etree.SubElement(metadata, f"{RDF}RDF", nsmap={"rdf": RDF_NS})
    work = rdf.find(f"{CC}Work")
    if work is None:
        work = etree.SubElement(rdf, f"{CC}Work", nsmap={"cc": CC_NS, "dc": DC_NS})
        # rdf:about is conventional on cc:Work; empty string means "this document".
        work.set(f"{RDF}about", "")
    return work


def _agent_title(work: etree._Element, field: str) -> str:
    el = work.find(f"{DC}{field}")
    if el is None:
        return ""
    agent = el.find(f"{CC}Agent")
    if agent is None:
        return el.text or ""
    title = agent.find(f"{DC}title")
    return (title.text or "") if title is not None else ""


def _set_agent_title(work: etree._Element, field: str, value: str) -> None:
    el = work.find(f"{DC}{field}")
    if el is None:
        el = etree.SubElement(work, f"{DC}{field}")
    # Reset to a clean Agent shape.
    for child in list(el):
        el.remove(child)
    el.text = None
    agent = etree.SubElement(el, f"{CC}Agent")
    title = etree.SubElement(agent, f"{DC}title")
    title.text = value


def _set_plain(work: etree._Element, field: str, value: str) -> None:
    el = work.find(f"{DC}{field}")
    if el is None:
        el = etree.SubElement(work, f"{DC}{field}")
    for child in list(el):
        el.remove(child)
    el.text = value


def _get_plain(work: etree._Element, field: str) -> str:
    el = work.find(f"{DC}{field}")
    return (el.text or "") if el is not None else ""


def _get_keywords(work: etree._Element) -> list[str]:
    subject = work.find(f"{DC}subject")
    if subject is None:
        return []
    bag = subject.find(f"{RDF}Bag")
    if bag is None:
        return []
    return [(li.text or "").strip() for li in bag.findall(f"{RDF}li") if (li.text or "").strip()]


def _set_keywords(work: etree._Element, keywords: list[str]) -> None:
    subject = work.find(f"{DC}subject")
    if subject is None:
        subject = etree.SubElement(work, f"{DC}subject")
    for child in list(subject):
        subject.remove(child)
    bag = etree.SubElement(subject, f"{RDF}Bag")
    for kw in keywords:
        li = etree.SubElement(bag, f"{RDF}li")
        li.text = kw


def _parse(input_path: str) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(input_path, parser)


def _write(tree: etree._ElementTree, output_path: str) -> None:
    from ._svg_io import write_tree

    write_tree(tree, output_path)


def _result(
    success: bool,
    operation: str,
    message: str,
    data: dict[str, Any],
    start: float,
    error: str = "",
) -> dict[str, Any]:
    return MetadataResult(
        success=success,
        operation=operation,
        message=message,
        data=data,
        execution_time_ms=(time.time() - start) * 1000,
        error=error,
    ).model_dump()


async def inkscape_metadata(
    operation: str,
    input_path: str,
    output_path: str = "",
    value: str = "",
    cli_wrapper: Any = None,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Get or set Dublin-Core fields in the document's <metadata> RDF block."""
    start = time.time()
    try:
        if not input_path:
            return _result(False, operation, "input_path required", {}, start, "ValueError")
        tree = _parse(input_path)
        root = tree.getroot()

        if operation == "get":
            metadata = root.find(f"{SVG}metadata")
            if metadata is None:
                return _result(
                    True,
                    operation,
                    "no metadata block",
                    {"title": "", "creator": "", "description": "", "rights": "", "keywords": []},
                    start,
                )
            work = _ensure_scaffold(root)
            data = {
                "title": _get_plain(work, "title"),
                "creator": _agent_title(work, "creator"),
                "description": _get_plain(work, "description"),
                "rights": _agent_title(work, "rights"),
                "keywords": _get_keywords(work),
            }
            return _result(True, operation, "metadata read", data, start)

        work = _ensure_scaffold(root)

        if operation == "set_title":
            _set_plain(work, "title", value)
        elif operation == "set_creator":
            _set_agent_title(work, "creator", value)
        elif operation == "set_description":
            _set_plain(work, "description", value)
        elif operation == "set_rights":
            _set_agent_title(work, "rights", value)
        elif operation == "set_keywords":
            keywords = [k.strip() for k in value.split(",") if k.strip()]
            _set_keywords(work, keywords)
        else:
            return _result(False, operation, f"unknown operation: {operation}", {}, start, "ValueError")

        out = output_path or input_path
        _write(tree, out)
        return _result(
            True,
            operation,
            f"updated {operation.replace('set_', '')}",
            {"input_path": input_path, "output_path": out, "value": value},
            start,
        )

    except Exception as e:
        return _result(False, operation, f"metadata op failed: {e}", {}, start, type(e).__name__)
