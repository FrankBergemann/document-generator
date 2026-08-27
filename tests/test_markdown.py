from __future__ import annotations

from cv_generator.markdown import inline_children, to_html, to_tree


class TestToHTML:
    def test_renders_commonmark(self) -> None:
        assert to_html("- one\n- two") == "<ul>\n<li>one</li>\n<li>two</li>\n</ul>"

    def test_tables_are_enabled(self) -> None:
        assert "<table>" in to_html("| a | b |\n| --- | --- |\n| 1 | 2 |")

    def test_strikethrough_is_enabled(self) -> None:
        assert "<s>" in to_html("~~gone~~")

    def test_empty_input(self) -> None:
        assert to_html("") == ""


class TestToTree:
    def test_block_types(self) -> None:
        tree = to_tree("Text.\n\n## Heading\n\n- item\n")
        assert [node.type for node in tree.children] == ["paragraph", "heading", "bullet_list"]

    def test_heading_level_is_on_the_tag(self) -> None:
        assert to_tree("### Role\n").children[0].tag == "h3"

    def test_link_href_is_available(self) -> None:
        paragraph = to_tree("[label](https://example.com)").children[0]
        link = inline_children(paragraph)[0]
        assert link.type == "link"
        assert link.attrs["href"] == "https://example.com"


class TestInlineChildren:
    def test_unwraps_the_inline_node(self) -> None:
        paragraph = to_tree("plain **bold** tail").children[0]
        assert [node.type for node in inline_children(paragraph)] == ["text", "strong", "text"]

    def test_block_without_inline_content(self) -> None:
        assert inline_children(to_tree("- item").children[0]) == []

    def test_both_renderers_see_the_same_source(self) -> None:
        # The point of the shared module: HTML and Word cannot drift apart
        # because there is only one parser configuration.
        markdown = "~~gone~~"
        assert "<s>" in to_html(markdown)
        assert inline_children(to_tree(markdown).children[0])[0].type == "s"
