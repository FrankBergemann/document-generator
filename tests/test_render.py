from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.errors import RenderError
from cv_generator.models import (
    Contact,
    Document,
    Link,
    RichCell,
    RichParagraph,
    RichRun,
    RichTable,
    Section,
)
from cv_generator.parser import load_doc, parse_doc
from cv_generator.render import Renderer, blocks_to_html
from tests.conftest import PROJECTS_CONFIG, PROJECTS_MD, write_config
from tests.support import PROJEKTLISTE_NAME, SAMPLE_PROJECTS, Project, write_projektliste


@pytest.fixture
def renderer() -> Renderer:
    return Renderer()


class TestAvailableThemes:
    def test_classic_is_bundled(self, renderer: Renderer) -> None:
        assert "classic" in renderer.available_themes()

    def test_empty_directory_has_no_themes(self, tmp_path: Path) -> None:
        assert Renderer(tmp_path).available_themes() == []


class TestRenderHTML:
    def test_produces_a_full_document(self, renderer: Renderer, minimal_document: Document) -> None:
        html = renderer.render_html(minimal_document)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_inlines_the_stylesheet_unescaped(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        html = renderer.render_html(minimal_document)
        # A child selector must survive as ">" - escaping it would break the CSS.
        assert ".cv-summary > p:first-child" in html
        assert "&gt; p:first-child" not in html

    def test_includes_identity_and_contact(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        html = renderer.render_html(minimal_document)
        assert "Ada Lovelace" in html
        assert 'href="mailto:ada@example.com"' in html
        assert 'href="https://example.com/notes"' in html

    def test_sections_become_anchored_elements(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        html = renderer.render_html(minimal_document)
        assert 'id="experience"' in html
        assert 'id="skills"' in html
        assert "<h2>Experience</h2>" in html

    def test_section_markdown_is_converted(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        html = renderer.render_html(minimal_document)
        assert "<li>Wrote Note G.</li>" in html
        assert "&lt;li&gt;" not in html

    def test_summary_markdown_is_converted(self, renderer: Renderer) -> None:
        doc = parse_doc("---\nname: Ada\n---\nA **strong** summary.\n")
        assert "<strong>strong</strong>" in renderer.render_html(doc)

    def test_rich_markdown_survives(self, renderer: Renderer, rich_document: Document) -> None:
        html = renderer.render_html(rich_document)
        for fragment in ("<table>", "<blockquote>", "<code>", "<s>", "<ol>", "<hr />"):
            assert fragment in html

    def test_lang_comes_from_the_model(self, renderer: Renderer) -> None:
        doc = parse_doc("---\nname: Ada\nlang: en\n---\n")
        assert '<html lang="en">' in renderer.render_html(doc)

    def test_contact_block_omitted_when_empty(self, renderer: Renderer) -> None:
        doc = Document(name="Ada")
        assert 'class="cv-contact"' not in renderer.render_html(doc)

    def test_theme_argument_overrides_the_model(self, renderer: Renderer) -> None:
        doc = Document(name="Ada", theme="does-not-exist")
        assert renderer.render_html(doc, "classic").startswith("<!DOCTYPE html>")

    def test_unknown_theme_lists_the_alternatives(self, renderer: Renderer) -> None:
        doc = Document(name="Ada", theme="brutalist")
        with pytest.raises(RenderError, match="classic"):
            renderer.render_html(doc)

    def test_user_content_is_escaped(self, renderer: Renderer) -> None:
        doc = Document(name="<script>alert(1)</script>", contact=Contact(location="a & b"))
        html = renderer.render_html(doc)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "a &amp; b" in html

    def test_link_labels_are_escaped(self, renderer: Renderer) -> None:
        doc = Document(
            name="Ada", contact=Contact(links=[Link(label="A & B", url="https://x.test")])
        )
        assert "A &amp; B" in renderer.render_html(doc)

    def test_print_page_size_is_declared_for_the_pdf_engine(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        # The chrome engine defers page geometry to the stylesheet, so losing
        # this rule would silently change the PDF's paper size.
        assert "size: A4" in renderer.render_html(minimal_document)


class TestImportedBlocks:
    """A section imported from a .docx renders as HTML, keeping its formatting."""

    @pytest.fixture
    def html(self, renderer: Renderer, projects_document: Document) -> str:
        return renderer.render_html(projects_document)

    def test_each_project_is_a_table(self, html: str) -> None:
        assert html.count('<table class="cv-block-table cv-block-table--ruled">') == len(
            SAMPLE_PROJECTS
        )

    def test_column_widths_come_from_the_document(self, html: str) -> None:
        assert '<col style="width:20%">' in html
        assert '<col style="width:80%">' in html

    def test_bold_and_size_survive_as_markup(self, html: str) -> None:
        assert '<span style="font-size:10pt"><strong>Rolle:</strong></span>' in html

    def test_bullets_become_a_list(self, html: str) -> None:
        assert "<ul><li>" in html
        assert "Aufbau der Testautomatisierung" in html

    def test_nested_bullet_sits_inside_its_parent_item(self, html: str) -> None:
        # A sibling <ul> would render at the wrong indent in the PDF.
        assert "</span><ul><li>" in html

    def test_hyperlink_becomes_an_anchor(self, html: str) -> None:
        assert '<a href="https://example.org/projekt">' in html

    def test_the_markdown_body_of_the_section_is_not_rendered(self, html: str) -> None:
        assert "darf nicht" not in html

    def test_imported_section_may_break_across_pages(self, html: str) -> None:
        # It is one section holding every project, so it cannot be kept whole;
        # the individual project tables are what must not be split.
        assert 'class="cv-section cv-section--blocks" id="projekte"' in html
        assert ".cv-section--blocks {\n  break-inside: auto;\n}" in html

    def test_text_from_the_document_is_escaped(self, renderer: Renderer, tmp_path: Path) -> None:
        write_projektliste(
            tmp_path / PROJEKTLISTE_NAME,
            [Project(period="2026", role="<script>alert(1)</script>", customer="a & b")],
        )
        (tmp_path / "document.md").write_text(PROJECTS_MD, encoding="utf-8")
        html = renderer.render_html(load_doc(write_config(tmp_path, PROJECTS_CONFIG)).doc)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "a &amp; b" in html


def _one_cell_table(*, centered: bool, column_widths: list[float] | None = None) -> RichTable:
    cell = RichCell(paragraphs=[RichParagraph(runs=[RichRun(text="x")])])
    return RichTable(
        rows=[[cell, cell]],
        centered=centered,
        column_widths=column_widths or [],
    )


class TestCenteredTable:
    """An `.xlsx` import sizes its table to its content and centers it."""

    def test_a_centered_table_gets_the_class(self) -> None:
        html = blocks_to_html([_one_cell_table(centered=True)])
        assert '<table class="cv-block-table cv-block-table--centered">' in html

    def test_a_non_centered_table_does_not(self) -> None:
        html = blocks_to_html([_one_cell_table(centered=False)])
        assert '<table class="cv-block-table">' in html
        assert "cv-block-table--centered" not in html

    def test_a_centered_table_ignores_its_column_widths(self) -> None:
        # The source's proportions would misdescribe a table sized to its own
        # content instead of stretched to fill the page.
        html = blocks_to_html([_one_cell_table(centered=True, column_widths=[0.5, 0.5])])
        assert "<colgroup>" not in html

    def test_a_non_centered_table_keeps_its_column_widths(self) -> None:
        html = blocks_to_html([_one_cell_table(centered=False, column_widths=[0.5, 0.5])])
        assert "<colgroup>" in html
        assert html.count('<col style="width:50%">') == 2


class TestPhoto:
    def test_photo_is_embedded_not_linked(
        self, renderer: Renderer, photo_document: Document
    ) -> None:
        # A src="portrait.png" would render here and vanish when the document is
        # printed by a browser in another container.
        html = renderer.render_html(photo_document)
        assert 'class="cv-photo" src="data:image/png;base64,' in html
        assert "portrait.png" not in html

    def test_embedded_bytes_are_the_file(
        self, renderer: Renderer, photo_document: Document
    ) -> None:
        assert photo_document.photo is not None
        assert photo_document.photo.data_uri() in renderer.render_html(photo_document)

    def test_alt_text_names_the_person(self, renderer: Renderer, photo_document: Document) -> None:
        assert f'alt="{photo_document.name}"' in renderer.render_html(photo_document)

    def test_sits_beside_the_identity_block_in_the_header(
        self, renderer: Renderer, photo_document: Document
    ) -> None:
        html = renderer.render_html(photo_document)
        header = html[html.index('<header class="cv-header">') : html.index("</header>")]
        assert header.index('class="cv-identity"') < header.index('class="cv-photo"')

    def test_header_is_a_row_with_the_photo_last(
        self, renderer: Renderer, photo_document: Document
    ) -> None:
        # The photo hugs the right margin because the header is a flex row and
        # the identity block takes the slack, not because of a float.
        css = renderer.render_html(photo_document)
        assert "display: flex" in css
        assert "flex: 1 1 auto" in css

    def test_the_photo_sets_the_header_height(
        self, renderer: Renderer, photo_document: Document
    ) -> None:
        # Fixed width, automatic height: shrinking the photo to the old header
        # height is exactly what must not happen.
        html = renderer.render_html(photo_document)
        assert "--photo-width: 34mm" in html
        assert "--photo-max-height: 48mm" in html
        assert "height: auto" in html

    def test_no_image_element_without_a_photo(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        assert "<img" not in renderer.render_html(minimal_document)

    def test_identity_block_wraps_the_header_text_either_way(
        self, renderer: Renderer, minimal_document: Document
    ) -> None:
        # The wrapper is unconditional, so the photo and photoless headers share
        # one set of CSS rules.
        assert 'class="cv-identity"' in renderer.render_html(minimal_document)


class TestUntitledSection:
    def test_no_heading_element_when_the_title_is_none(self, renderer: Renderer) -> None:
        doc = Document(sections=[Section(title=None, slug="letterhead", markdown="Body text.")])
        html = renderer.render_html(doc)
        assert "<h2>" not in html
        assert "Body text." in html

    def test_the_section_and_its_anchor_are_still_there(self, renderer: Renderer) -> None:
        doc = Document(sections=[Section(title=None, slug="letterhead", markdown="Body text.")])
        html = renderer.render_html(doc)
        assert 'id="letterhead"' in html

    def test_a_titled_section_still_gets_its_heading(self, renderer: Renderer) -> None:
        doc = Document(
            sections=[Section(title="Kenntnisse", slug="kenntnisse", markdown="- Python")]
        )
        assert "<h2>Kenntnisse</h2>" in renderer.render_html(doc)


class TestPageHeader:
    def test_page_header_content_is_rendered(self, renderer: Renderer) -> None:
        doc = Document(page_header=[RichParagraph(runs=[RichRun(text="Header text")])])
        html = renderer.render_html(doc)
        assert '<header class="cv-page-header">' in html
        assert "Header text" in html

    def test_no_page_header_element_without_content(self, renderer: Renderer) -> None:
        # The stylesheet mentions "cv-page-header" regardless (its CSS rule is
        # always inlined), so this checks for the element with that class.
        doc = Document(name="Ada")
        assert 'class="cv-page-header"' not in renderer.render_html(doc)

    def test_page_header_text_is_escaped(self, renderer: Renderer) -> None:
        doc = Document(
            page_header=[RichParagraph(runs=[RichRun(text="<script>alert(1)</script>")])]
        )
        html = renderer.render_html(doc)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestPageFooter:
    def test_page_footer_content_is_rendered(self, renderer: Renderer) -> None:
        doc = Document(page_footer=[RichParagraph(runs=[RichRun(text="Footer text")])])
        html = renderer.render_html(doc)
        assert '<footer class="cv-page-footer">' in html
        assert "Footer text" in html

    def test_no_page_footer_element_without_content(self, renderer: Renderer) -> None:
        # The stylesheet mentions "cv-page-footer" regardless (its CSS rule is
        # always inlined), so this checks for the <footer> element itself.
        doc = Document(name="Ada")
        assert "<footer" not in renderer.render_html(doc)

    def test_page_footer_text_is_escaped(self, renderer: Renderer) -> None:
        doc = Document(
            page_footer=[RichParagraph(runs=[RichRun(text="<script>alert(1)</script>")])]
        )
        html = renderer.render_html(doc)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestEmptyHeader:
    """A recipe with nothing to put in the header gets no header at all --
    not an empty one with a rule drawn under nothing."""

    def test_no_header_element_when_completely_bare(self, renderer: Renderer) -> None:
        doc = Document(sections=[Section(title="Kenntnisse", slug="kenntnisse", markdown="x")])
        assert "<header" not in renderer.render_html(doc)

    def test_a_name_alone_still_gets_a_header(self, renderer: Renderer) -> None:
        doc = Document(name="Ada")
        assert "<header" in renderer.render_html(doc)

    def test_a_headline_alone_still_gets_a_header(self, renderer: Renderer) -> None:
        doc = Document(headline="Mathematician")
        assert "<header" in renderer.render_html(doc)

    def test_contact_details_alone_still_get_a_header(self, renderer: Renderer) -> None:
        doc = Document(contact=Contact(email="ada@example.com"))
        assert "<header" in renderer.render_html(doc)
