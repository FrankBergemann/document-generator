"""The single Markdown parser shared by every output backend.

Two consumers with different needs: the HTML renderer wants a string, the Word
renderer wants to walk the structure. Both come from the same configured
``MarkdownIt`` instance, so a Markdown feature enabled here is available in
every output format at once.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

_MARKDOWN = MarkdownIt("commonmark").enable(["table", "strikethrough"])


def to_html(text: str) -> str:
    """Render a Markdown fragment to an HTML fragment."""
    html: str = _MARKDOWN.render(text)
    return html.strip()


def to_tree(text: str) -> SyntaxTreeNode:
    """Parse a Markdown fragment into a nested syntax tree.

    The root node is a container; ``root.children`` are the block-level nodes
    (``paragraph``, ``heading``, ``bullet_list``, ``table``, ...).
    """
    return SyntaxTreeNode(_MARKDOWN.parse(text))


def inline_children(node: SyntaxTreeNode) -> list[SyntaxTreeNode]:
    """Return the inline nodes inside a block node such as a paragraph.

    markdown-it wraps a block's inline content in a single ``inline`` node;
    this unwraps it, returning ``[]`` for blocks that have no inline content.
    """
    for child in node.children:
        if child.type == "inline":
            return list(child.children)
    return []
