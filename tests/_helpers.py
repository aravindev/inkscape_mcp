"""Small helpers shared across test modules."""

from __future__ import annotations


def payload(result):
    """Unwrap a FastMCP tool result into its dict payload."""
    if result.structured_content is not None:
        return result.structured_content
    if result.data is not None:
        return result.data
    return {"text": "\n".join(b.text for b in result.content if hasattr(b, "text"))}
