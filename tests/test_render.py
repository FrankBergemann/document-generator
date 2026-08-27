from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.errors import RenderError
from cv_generator.models import CV, Contact, Link
from cv_generator.parser import parse_cv, parse_cv_file
from cv_generator.render import Renderer
from tests.conftest import PROJECTS_MD
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
    def test_produces_a_full_document(self, renderer: Renderer, minimal_cv: CV) -> None:
        html = renderer.render_html(minimal_cv)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_inlines_the_stylesheet_unescaped(self, renderer: Renderer, minimal_cv: CV) -> None:
        html = renderer.render_html(minimal_cv)
        # A child selector must survive as ">" - escaping it would break the CSS.
        assert ".cv-summary > p:first-child" in html
        assert "&gt; p:first-child" not in html

    def test_includes_identity_and_contact(self, renderer: Renderer, minimal_cv: CV) -> None:
        html = renderer.render_html(minimal_cv)
        assert "Ada Lovelace" in html
        assert 'href="mailto:ada@example.com"' in html
        assert 'href="https://example.com/notes"' in html

    def test_sections_become_anchored_elements(self, renderer: Renderer, minimal_cv: CV) -> None:
        html = renderer.render_html(minimal_cv)
        assert 'id="experience"' in html
        assert 'id="skills"' in html
        assert "<h2>Experience</h2>" in html

    def test_section_markdown_is_converted(self, renderer: Renderer, minimal_cv: CV) -> None:
        html = renderer.render_html(minimal_cv)
        assert "<li>Wrote Note G.</li>" in html
        assert "&lt;li&gt;" not in html

    def test_summary_markdown_is_converted(self, renderer: Renderer) -> None:
        cv = parse_cv("---\nname: Ada\n---\nA **strong** summary.\n")
        assert "<strong>strong</strong>" in renderer.render_html(cv)

    def test_rich_markdown_survives(self, renderer: Renderer, rich_cv: CV) -> None:
        html = renderer.render_html(rich_cv)
        for fragment in ("<table>", "<blockquote>", "<code>", "<s>", "<ol>", "<hr />"):
            assert fragment in html

    def test_lang_comes_from_the_model(self, renderer: Renderer) -> None:
        cv = parse_cv("---\nname: Ada\nlang: en\n---\n")
        assert '<html lang="en">' in renderer.render_html(cv)

    def test_contact_block_omitted_when_empty(self, renderer: Renderer) -> None:
        cv = CV(name="Ada")
        assert 'class="cv-contact"' not in renderer.render_html(cv)

    def test_theme_argument_overrides_the_model(self, renderer: Renderer) -> None:
        cv = CV(name="Ada", theme="does-not-exist")
        assert renderer.render_html(cv, "classic").startswith("<!DOCTYPE html>")

    def test_unknown_theme_lists_the_alternatives(self, renderer: Renderer) -> None:
        cv = CV(name="Ada", theme="brutalist")
        with pytest.raises(RenderError, match="classic"):
            renderer.render_html(cv)

    def test_user_content_is_escaped(self, renderer: Renderer) -> None:
        cv = CV(name="<script>alert(1)</script>", contact=Contact(location="a & b"))
        html = renderer.render_html(cv)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "a &amp; b" in html

    def test_link_labels_are_escaped(self, renderer: Renderer) -> None:
        cv = CV(name="Ada", contact=Contact(links=[Link(label="A & B", url="https://x.test")]))
        assert "A &amp; B" in renderer.render_html(cv)

    def test_print_page_size_is_declared_for_the_pdf_engine(
        self, renderer: Renderer, minimal_cv: CV
    ) -> None:
        # The chrome engine defers page geometry to the stylesheet, so losing
        # this rule would silently change the PDF's paper size.
        assert "size: A4" in renderer.render_html(minimal_cv)


class TestImportedBlocks:
    """A section imported from a .docx renders as HTML, keeping its formatting."""

    @pytest.fixture
    def html(self, renderer: Renderer, projects_cv: CV) -> str:
        return renderer.render_html(projects_cv)

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
        path = tmp_path / "cv.md"
        path.write_text(PROJECTS_MD, encoding="utf-8")
        html = renderer.render_html(parse_cv_file(path))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "a &amp; b" in html


class TestPhoto:
    def test_photo_is_embedded_not_linked(self, renderer: Renderer, photo_cv: CV) -> None:
        # A src="portrait.png" would render here and vanish when the document is
        # printed by a browser in another container.
        html = renderer.render_html(photo_cv)
        assert 'class="cv-photo" src="data:image/png;base64,' in html
        assert "portrait.png" not in html

    def test_embedded_bytes_are_the_file(self, renderer: Renderer, photo_cv: CV) -> None:
        assert photo_cv.photo is not None
        assert photo_cv.photo.data_uri() in renderer.render_html(photo_cv)

    def test_alt_text_names_the_person(self, renderer: Renderer, photo_cv: CV) -> None:
        assert f'alt="{photo_cv.name}"' in renderer.render_html(photo_cv)

    def test_sits_beside_the_identity_block_in_the_header(
        self, renderer: Renderer, photo_cv: CV
    ) -> None:
        html = renderer.render_html(photo_cv)
        header = html[html.index('<header class="cv-header">') : html.index("</header>")]
        assert header.index('class="cv-identity"') < header.index('class="cv-photo"')

    def test_header_is_a_row_with_the_photo_last(self, renderer: Renderer, photo_cv: CV) -> None:
        # The photo hugs the right margin because the header is a flex row and
        # the identity block takes the slack, not because of a float.
        css = renderer.render_html(photo_cv)
        assert "display: flex" in css
        assert "flex: 1 1 auto" in css

    def test_the_photo_sets_the_header_height(self, renderer: Renderer, photo_cv: CV) -> None:
        # Fixed width, automatic height: shrinking the photo to the old header
        # height is exactly what must not happen.
        html = renderer.render_html(photo_cv)
        assert "--photo-width: 34mm" in html
        assert "--photo-max-height: 48mm" in html
        assert "height: auto" in html

    def test_no_image_element_without_a_photo(self, renderer: Renderer, minimal_cv: CV) -> None:
        assert "<img" not in renderer.render_html(minimal_cv)

    def test_identity_block_wraps_the_header_text_either_way(
        self, renderer: Renderer, minimal_cv: CV
    ) -> None:
        # The wrapper is unconditional, so the photo and photoless headers share
        # one set of CSS rules.
        assert 'class="cv-identity"' in renderer.render_html(minimal_cv)
