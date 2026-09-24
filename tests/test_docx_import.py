from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import docx
import pytest
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph as WordParagraph
from docx.text.run import Run

from cv_generator.docx_import import load_footer, load_section
from cv_generator.errors import DocParseError
from cv_generator.models import RichBlock, RichParagraph, RichRun, RichTable
from tests.support import (
    AFTER_SECTION,
    BEFORE_HEADING,
    BODY_SIZE_PT,
    INHERITS_BOLD,
    PROJEKTLISTE_NAME,
    SAMPLE_PROJECTS,
    SPLIT_RUNS,
    SWITCHED_OFF,
    png,
    write_projektliste,
    write_styled_docx,
)


@pytest.fixture
def projektliste(tmp_path: Path) -> Path:
    return write_projektliste(tmp_path / PROJEKTLISTE_NAME)


@pytest.fixture
def blocks(projektliste: Path) -> list[RichBlock]:
    return load_section(projektliste, "Projekthistorie")


def tables(blocks: list[RichBlock]) -> list[RichTable]:
    return [block for block in blocks if isinstance(block, RichTable)]


def cell_paragraphs(blocks: list[RichBlock]) -> list[RichParagraph]:
    return [
        paragraph
        for table in tables(blocks)
        for row in table.rows
        for cell in row
        for paragraph in cell.paragraphs
    ]


def runs(blocks: list[RichBlock]) -> list[RichRun]:
    return [run for paragraph in cell_paragraphs(blocks) for run in paragraph.runs]


def texts(blocks: list[RichBlock]) -> list[str]:
    """Every paragraph's text, inside tables too, for absence assertions."""
    top_level = [block.text() for block in blocks if isinstance(block, RichParagraph)]
    return top_level + [paragraph.text() for paragraph in cell_paragraphs(blocks)]


class TestNamedEnd:
    """A build recipe may say which heading the import stops before."""

    def test_the_end_heading_is_not_imported(self, projektliste: Path) -> None:
        blocks = load_section(projektliste, "Projekthistorie", "Ausbildung")
        assert "Ausbildung" not in texts(blocks)
        assert AFTER_SECTION not in texts(blocks)
        assert len(tables(blocks)) == len(SAMPLE_PROJECTS)

    def test_it_overrides_the_formatting_rule(self, projektliste: Path) -> None:
        # Left to itself the import would stop at "Ausbildung", which is shaped
        # like the heading it started from. Naming a later paragraph carries that
        # heading in, which is how a recipe overrules the guess.
        blocks = load_section(projektliste, "Projekthistorie", AFTER_SECTION)
        assert "Ausbildung" in texts(blocks)
        assert AFTER_SECTION not in texts(blocks)

    def test_it_is_matched_case_insensitively(self, projektliste: Path) -> None:
        assert load_section(projektliste, "Projekthistorie", "AUSBILDUNG")

    def test_it_may_be_a_regular_expression(self, projektliste: Path) -> None:
        blocks = load_section(projektliste, "Projekthistorie", "Ausbild.*")
        assert "Ausbildung" not in texts(blocks)

    def test_a_regular_expression_still_matches_the_whole_heading(self, projektliste: Path) -> None:
        # Not a substring search: "Ausbild" alone must not match "Ausbildung" --
        # otherwise a paragraph merely mentioning a heading's name would be
        # mistaken for the heading itself.
        with pytest.raises(DocParseError, match="no heading matching 'Ausbild' follows"):
            load_section(projektliste, "Projekthistorie", "Ausbild")

    def test_an_invalid_regular_expression_is_a_clean_error(self, projektliste: Path) -> None:
        with pytest.raises(DocParseError, match="not a valid regular expression"):
            load_section(projektliste, "Projekthistorie", "Ausbildung(")

    def test_an_end_that_never_comes_is_an_error(self, projektliste: Path) -> None:
        # Not "run to the end of the document": the recipe said where to stop,
        # so importing the rest would put another section's content in this one.
        with pytest.raises(DocParseError, match="no heading matching 'Publikationen' follows"):
            load_section(projektliste, "Projekthistorie", "Publikationen")

    def test_an_end_before_the_beginning_does_not_count(self, projektliste: Path) -> None:
        with pytest.raises(DocParseError, match="no heading matching 'Profil' follows"):
            load_section(projektliste, "Projekthistorie", "Profil")

    def test_end_may_match_a_line_whose_wording_varies(self, tmp_path: Path) -> None:
        # A form letter's closing line names a value (here, a payment term) that
        # changes from one letter to the next, so no fixed string names it -- a
        # wildcard standing in for the variable part still covers the whole line.
        document = docx.Document()
        document.add_paragraph("Vielen Dank für Ihr Vertrauen.")
        document.add_paragraph("Bitte überweisen Sie den Betrag innerhalb von 14 Tagen.")
        document.add_paragraph("Anlage: Rechnungsdetails")
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(
            path, end=r"Bitte überweisen Sie den Betrag innerhalb von \d+ Tagen\."
        )
        assert "Vielen Dank für Ihr Vertrauen." in texts(blocks)
        assert "Bitte überweisen" not in texts(blocks)
        assert "Anlage: Rechnungsdetails" not in texts(blocks)


class TestSectionBoundaries:
    def test_one_table_per_project(self, blocks: list[RichBlock]) -> None:
        assert len(tables(blocks)) == len(SAMPLE_PROJECTS)

    def test_the_blank_paragraphs_between_tables_are_kept(self, blocks: list[RichBlock]) -> None:
        # The source needs one to keep two tables from merging when Word
        # renders them, and it is otherwise indistinguishable from any other
        # blank line -- so, like any other blank paragraph, it is kept.
        assert len(blocks) == 2 * len(SAMPLE_PROJECTS) + 1

    def test_earlier_sections_are_not_imported(self, blocks: list[RichBlock]) -> None:
        assert BEFORE_HEADING not in texts(blocks)

    def test_import_stops_at_the_next_heading(self, blocks: list[RichBlock]) -> None:
        assert AFTER_SECTION not in texts(blocks)

    def test_heading_is_matched_case_insensitively(self, projektliste: Path) -> None:
        assert load_section(projektliste, "projekthistorie")

    def test_heading_may_be_a_regular_expression(self, projektliste: Path) -> None:
        assert load_section(projektliste, "Projekt.*orie")

    def test_blank_paragraph_inside_a_cell_is_kept(self, blocks: list[RichBlock]) -> None:
        period = tables(blocks)[0].rows[0][0]
        assert [paragraph.text() for paragraph in period.paragraphs] == [
            "02/2026 – 07/2026",
            "Rolle:",
            "programmweiter Testmanager",
            "",
            "Kunde:",
            "Land Schleswig-Holstein",
        ]

    def test_missing_heading_is_an_error(self, projektliste: Path) -> None:
        with pytest.raises(DocParseError, match="no heading matching 'Projekte' found"):
            load_section(projektliste, "Projekte")

    def test_a_section_of_only_blank_paragraphs_is_not_empty(self, tmp_path: Path) -> None:
        # Blank paragraphs are content now (they preserve the source's own
        # spacing), so a section that is only blank lines is not the same as
        # no section at all.
        path = write_projektliste(tmp_path / PROJEKTLISTE_NAME, [])
        blocks = load_section(path, "Projekthistorie", "Ausbildung")
        assert len(blocks) == 1
        assert blocks[0].text() == ""  # type: ignore[union-attr]

    def test_a_heading_immediately_followed_by_the_end_is_an_error(self, tmp_path: Path) -> None:
        # Nothing at all between the two headings, not even a blank paragraph.
        document = docx.Document()
        document.add_paragraph("Start")
        document.add_paragraph("End")
        path = tmp_path / "brief.docx"
        document.save(str(path))
        with pytest.raises(DocParseError, match="nothing follows the heading"):
            load_section(path, "Start", "End")

    def test_a_file_that_is_not_a_word_document(self, tmp_path: Path) -> None:
        path = tmp_path / "Projektliste.docx"
        path.write_text("just text", encoding="utf-8")
        with pytest.raises(DocParseError, match="as a Word document"):
            load_section(path, "Projekthistorie")


class TestFormatting:
    def test_bold_and_size_are_carried_over(self, blocks: list[RichBlock]) -> None:
        period = tables(blocks)[0].rows[0][0].paragraphs
        assert [(run.text, run.bold, run.size_pt) for run in period[0].runs] == [
            ("02/2026 – 07/2026", True, BODY_SIZE_PT)
        ]
        assert period[2].runs[0].bold is False

    def test_style_is_resolved_and_a_run_can_switch_it_off(self, tmp_path: Path) -> None:
        path = write_styled_docx(tmp_path / "Projektliste.docx")
        styled = load_section(path, "Projekthistorie")[0]
        assert isinstance(styled, RichParagraph)
        assert [(run.text, run.bold) for run in styled.runs] == [
            (INHERITS_BOLD, True),
            (SWITCHED_OFF, False),
        ]

    def test_neighbouring_runs_of_equal_formatting_are_merged(self, tmp_path: Path) -> None:
        # Word splits a sentence at every spell-check marker and revision; left
        # alone, each fragment would become its own <span> and its own Word run.
        path = write_styled_docx(tmp_path / "Projektliste.docx")
        split = load_section(path, "Projekthistorie")[1]
        assert isinstance(split, RichParagraph)
        assert [run.text for run in split.runs] == ["".join(SPLIT_RUNS)]

    def test_hyperlink_keeps_its_text_and_target(self, blocks: list[RichBlock]) -> None:
        linked = [run for run in runs(blocks) if run.link]
        assert [(run.text, run.link) for run in linked] == [
            ("Projektseite", "https://example.org/projekt")
        ]


class TestBlankParagraphSize:
    """A blank paragraph is as tall as its paragraph mark's font size in Word,
    so that size is kept -- a blank line under a 24pt title is a 24pt line."""

    def test_the_mark_s_own_size_is_read(self, tmp_path: Path) -> None:
        document = docx.Document()
        blank = document.add_paragraph()
        blank._p.get_or_add_pPr().append(
            parse_xml(f'<w:rPr {nsdecls("w")}><w:sz w:val="48"/></w:rPr>')
        )
        path = tmp_path / "brief.docx"
        document.save(str(path))

        (paragraph,) = load_section(path)
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.blank_size_pt == 24.0

    def test_without_one_the_paragraph_style_s_size_is_used(self, tmp_path: Path) -> None:
        document = docx.Document()
        document.styles["Normal"].font.size = Pt(11)
        document.add_paragraph()
        path = tmp_path / "brief.docx"
        document.save(str(path))

        (paragraph,) = load_section(path)
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.blank_size_pt == 11.0

    def test_a_paragraph_with_text_takes_its_size_from_its_runs(self, tmp_path: Path) -> None:
        document = docx.Document()
        document.styles["Normal"].font.size = Pt(11)
        document.add_paragraph("Text")
        path = tmp_path / "brief.docx"
        document.save(str(path))

        (paragraph,) = load_section(path)
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.blank_size_pt is None


class TestAlignment:
    """A letterhead-style header commonly right-aligns its identity block
    (``w:jc``) -- dropping it turns "flush right" into "flush left", the same
    class of bug as dropping bold. See :func:`cv_generator.docx_import._alignment_of`."""

    def test_a_paragraph_s_own_alignment_is_read(self, tmp_path: Path) -> None:
        document = docx.Document()
        paragraph = document.add_paragraph("Right-aligned")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].alignment == "right"

    def test_no_jc_at_all_leaves_alignment_unset(self, tmp_path: Path) -> None:
        document = docx.Document()
        document.add_paragraph("Plain")
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].alignment is None

    def test_alignment_inherited_from_the_paragraph_style_is_read(self, tmp_path: Path) -> None:
        # Word's own header/footer letterhead paragraphs often carry their
        # jc on the style rather than directly -- the same "style, not the
        # paragraph" case _numbering_of already has to handle for bullets.
        document = docx.Document()
        style = document.styles.add_style("RightStyle", WD_STYLE_TYPE.PARAGRAPH)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        document.add_paragraph("Styled", style=style)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].alignment == "right"

    def test_a_direct_alignment_overrides_the_style_s(self, tmp_path: Path) -> None:
        document = docx.Document()
        style = document.styles.add_style("RightStyle2", WD_STYLE_TYPE.PARAGRAPH)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph = document.add_paragraph("Overridden", style=style)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].alignment == "center"

    def test_an_alignment_this_project_does_not_style_for_is_left_unset(
        self, tmp_path: Path
    ) -> None:
        # ST_Jc has values beyond the four CSS/Word alignments this project's
        # themes style for (distribute, the kashida variants, ...) -- an
        # explicit but unsupported value falls through to None rather than
        # guessing, the same as any other "not set here".
        document = docx.Document()
        paragraph = document.add_paragraph("Distributed")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.DISTRIBUTE
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].alignment is None


class TestLists:
    def test_bullets_become_list_items_at_their_level(self, blocks: list[RichBlock]) -> None:
        detail = tables(blocks)[0].rows[0][1].paragraphs
        assert [(p.text(), p.level, p.ordered) for p in detail] == [
            ("Tätigkeiten", None, False),
            ("Konzeption einer Integrationstestumgebung", 0, False),
            ("Aufbau der Testautomatisierung", 0, False),
            ("mit Playwright & TypeScript", 1, False),
            ("Projektseite", None, False),
        ]


class TestTableGeometry:
    def test_two_columns_with_their_widths(self, blocks: list[RichBlock]) -> None:
        table = tables(blocks)[0]
        assert [len(row) for row in table.rows] == [2]
        assert table.column_widths == pytest.approx([0.2, 0.8], abs=0.005)

    def test_a_ruled_table_says_so(self, blocks: list[RichBlock]) -> None:
        # `Table Grid` keeps its borders in the style, not on the table.
        assert all(table.bordered for table in tables(blocks))

    def test_a_docx_table_is_not_centered(self, blocks: list[RichBlock]) -> None:
        # Unlike an `.xlsx` range, a `.docx` table is meant to fill the page the
        # way it did in the source document.
        assert all(not table.centered for table in tables(blocks))
        assert all(not table.outer_rules for table in tables(blocks))

    def test_rules_above_and_below_are_kept_without_making_a_grid(self, tmp_path: Path) -> None:
        # A block of personal details ruled off above and below: not a grid,
        # but the two lines are part of what it looks like.
        table = _ruled_table(tmp_path, "top", "bottom")
        assert table.bordered is False
        assert table.outer_rules == ["top", "bottom"]

    def test_a_full_box_is_bordered_with_no_separate_rules(self, tmp_path: Path) -> None:
        table = _ruled_table(tmp_path, "bottom", "right", "top", "left")
        assert table.bordered is True
        assert table.outer_rules == []

    def test_a_vertically_merged_cell_is_read_once(self, tmp_path: Path) -> None:
        # `row.cells` hands back the merged cell for every row it spans, which
        # would repeat its content -- a portrait beside a block of details
        # would appear once per row.
        document = docx.Document()
        word_table = document.add_table(rows=3, cols=2)
        word_table.cell(0, 1).text = "Portrait"
        word_table.cell(0, 1).merge(word_table.cell(2, 1))
        for row in range(3):
            word_table.cell(row, 0).text = f"Row {row}"
        path = tmp_path / "merged.docx"
        document.save(str(path))

        (table,) = tables(load_section(path))
        assert [[cell.merged for cell in row] for row in table.rows] == [
            [False, False],
            [False, True],
            [False, True],
        ]
        assert table.rows[0][1].row_span == 3
        assert table.rows[0][1].paragraphs[0].text() == "Portrait"
        assert all(not row[1].paragraphs for row in table.rows[1:])


def _ruled_table(tmp_path: Path, *edges: str) -> RichTable:
    """The one table of a `.docx` whose own `w:tblBorders` rules `edges`."""
    document = docx.Document()
    word_table = document.add_table(rows=1, cols=1)
    word_table.cell(0, 0).text = "Cell"
    lines = "".join(f'<w:{edge} w:val="single" w:sz="12"/>' for edge in edges)
    word_table._tbl.tblPr.append(parse_xml(f"<w:tblBorders {nsdecls('w')}>{lines}</w:tblBorders>"))
    path = tmp_path / "ruled.docx"
    document.save(str(path))
    (table,) = tables(load_section(path))
    return table


def _write_footer_docx(path: Path, *, footer_paragraphs: list[str] | None = None) -> None:
    """A minimal `.docx` with a body paragraph and, optionally, a footer."""
    document = docx.Document()
    document.add_paragraph("Body content.")
    if footer_paragraphs:
        footer = document.sections[0].footer
        footer.is_linked_to_previous = False
        footer.paragraphs[0].text = footer_paragraphs[0]
        for text in footer_paragraphs[1:]:
            footer.add_paragraph(text)
    document.save(str(path))


def _append_runs(paragraph: WordParagraph, xml: str) -> None:
    """Append raw ``w:r``/``w:fldSimple`` elements to ``paragraph``."""
    for element in parse_xml(f"<w:p {nsdecls('w')}>{xml}</w:p>"):
        paragraph._p.append(element)


class TestPageBreaks:
    """``w:br w:type="page"`` and ``w:pageBreakBefore`` become the paragraph's
    ``page_break_before``/``page_break_after``."""

    def _body(self, tmp_path: Path, xml: str) -> list[RichParagraph]:
        document = docx.Document()
        paragraph = document.add_paragraph()
        _append_runs(paragraph, xml)
        path = tmp_path / "brief.docx"
        document.save(str(path))
        blocks = load_section(path)
        assert all(isinstance(block, RichParagraph) for block in blocks)
        return cast(list[RichParagraph], blocks)

    @staticmethod
    def _shape(paragraphs: list[RichParagraph]) -> list[tuple[str, bool, bool]]:
        return [(p.text(), p.page_break_before, p.page_break_after) for p in paragraphs]

    def test_a_paragraph_of_only_a_break_breaks_after_itself(self, tmp_path: Path) -> None:
        # The CV's own shape: the paragraph mark stays on the old page, so
        # this is one empty paragraph, not an empty line atop the next page.
        paragraphs = self._body(tmp_path, '<w:r><w:br w:type="page"/></w:r>')
        assert self._shape(paragraphs) == [("", False, True)]

    def test_a_break_mid_paragraph_splits_it(self, tmp_path: Path) -> None:
        paragraphs = self._body(
            tmp_path, '<w:r><w:t>Before</w:t><w:br w:type="page"/><w:t>After</w:t></w:r>'
        )
        assert self._shape(paragraphs) == [("Before", False, False), ("After", True, False)]

    def test_a_break_at_the_start_leaves_no_blank_line_behind(self, tmp_path: Path) -> None:
        paragraphs = self._body(tmp_path, '<w:r><w:br w:type="page"/><w:t>After</w:t></w:r>')
        assert self._shape(paragraphs) == [("After", True, False)]

    def test_a_plain_line_break_is_not_a_page_break(self, tmp_path: Path) -> None:
        paragraphs = self._body(tmp_path, "<w:r><w:t>One</w:t><w:br/><w:t>Two</w:t></w:r>")
        assert self._shape(paragraphs) == [("One\nTwo", False, False)]

    def test_page_break_before_is_read(self, tmp_path: Path) -> None:
        document = docx.Document()
        document.add_paragraph("New page").paragraph_format.page_break_before = True
        path = tmp_path / "brief.docx"
        document.save(str(path))
        (paragraph,) = load_section(path)
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.page_break_before is True

    def test_a_break_inside_a_table_cell_is_dropped(self, tmp_path: Path) -> None:
        # Word itself ignores it there: a cell cannot start a new page.
        document = docx.Document()
        cell = document.add_table(rows=1, cols=1).cell(0, 0)
        _append_runs(cell.paragraphs[0], '<w:r><w:t>A</w:t><w:br w:type="page"/><w:t>B</w:t></w:r>')
        path = tmp_path / "brief.docx"
        document.save(str(path))
        (table,) = tables(load_section(path))
        (paragraph,) = table.rows[0][0].paragraphs
        assert (paragraph.text(), paragraph.page_break_before) == ("AB", False)


class TestPageFields:
    """A "Seite 2 von 4" footer is two Word fields. Their cached result text
    is kept, marked with the field it belongs to, so a renderer with pages can
    compute it afresh."""

    def _footer_paragraph(self, tmp_path: Path, xml: str) -> RichParagraph:
        document = docx.Document()
        document.add_paragraph("Body")
        footer = document.sections[0].footer
        footer.is_linked_to_previous = False
        footer.paragraphs[0].add_run("Seite ")
        _append_runs(footer.paragraphs[0], xml)
        path = tmp_path / "brief.docx"
        document.save(str(path))
        (paragraph,) = load_footer(path)
        assert isinstance(paragraph, RichParagraph)
        return paragraph

    def test_a_complex_page_field_marks_its_result_run(self, tmp_path: Path) -> None:
        paragraph = self._footer_paragraph(
            tmp_path,
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>2</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:t xml:space="preserve"> von </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText>NUMPAGES</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>4</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
        )
        assert [(run.text, run.field) for run in paragraph.runs] == [
            ("Seite ", None),
            ("2", "page"),
            (" von ", None),
            ("4", "pages"),
        ]

    def test_a_simple_page_field_is_read_too(self, tmp_path: Path) -> None:
        paragraph = self._footer_paragraph(
            tmp_path, '<w:fldSimple w:instr=" PAGE "><w:r><w:t>2</w:t></w:r></w:fldSimple>'
        )
        assert [(run.text, run.field) for run in paragraph.runs] == [
            ("Seite ", None),
            ("2", "page"),
        ]

    def test_any_other_field_stays_plain_text(self, tmp_path: Path) -> None:
        paragraph = self._footer_paragraph(
            tmp_path,
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText>DATE</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>24.09.2026</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
        )
        assert [(run.text, run.field) for run in paragraph.runs] == [("Seite 24.09.2026", None)]


class TestFooter:
    def test_a_plain_footer_paragraph_is_read(self, tmp_path: Path) -> None:
        path = tmp_path / "brief.docx"
        _write_footer_docx(path, footer_paragraphs=["Footer line"])
        blocks = load_footer(path)
        assert len(blocks) == 1
        assert blocks[0].text() == "Footer line"  # type: ignore[union-attr]

    def test_a_document_with_no_footer_definition_returns_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "brief.docx"
        _write_footer_docx(path)
        assert load_footer(path) == []

    def test_blank_footer_paragraphs_are_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "brief.docx"
        _write_footer_docx(path, footer_paragraphs=["", "Real line", ""])
        blocks = load_footer(path)
        assert [b.text() for b in blocks] == ["", "Real line", ""]  # type: ignore[union-attr]

    def test_formatting_is_preserved(self, tmp_path: Path) -> None:
        document = docx.Document()
        document.add_paragraph("Body")
        footer = document.sections[0].footer
        footer.is_linked_to_previous = False
        run = footer.paragraphs[0].add_run("Bold footer")
        run.bold = True
        path = tmp_path / "brief.docx"
        document.save(str(path))
        blocks = load_footer(path)
        assert blocks[0].runs[0].bold is True  # type: ignore[union-attr]

    def test_the_first_page_footer_wins_when_it_has_content(self, tmp_path: Path) -> None:
        # A single-page letter shows only its first-page footer; the "default"
        # one, meant for a second page that never comes, is typically empty.
        document = docx.Document()
        document.add_paragraph("Body")
        section = document.sections[0]
        section.different_first_page_header_footer = True
        section.first_page_footer.is_linked_to_previous = False
        section.first_page_footer.paragraphs[0].text = "First-page footer"
        path = tmp_path / "brief.docx"
        document.save(str(path))
        blocks = load_footer(path)
        assert len(blocks) == 1
        assert blocks[0].text() == "First-page footer"  # type: ignore[union-attr]

    def test_the_default_footer_is_used_when_the_first_page_one_is_empty(
        self, tmp_path: Path
    ) -> None:
        document = docx.Document()
        document.add_paragraph("Body")
        section = document.sections[0]
        section.different_first_page_header_footer = True
        section.footer.is_linked_to_previous = False
        section.footer.paragraphs[0].text = "Default footer"
        path = tmp_path / "brief.docx"
        document.save(str(path))
        blocks = load_footer(path)
        assert len(blocks) == 1
        assert blocks[0].text() == "Default footer"  # type: ignore[union-attr]

    def test_a_text_box_s_alternate_content_is_read_only_once(self, tmp_path: Path) -> None:
        # A letterhead-style footer commonly anchors its content in a text box,
        # written twice in the XML -- once as the modern shape (`mc:Choice`),
        # once as a legacy fallback (`mc:Fallback`) for a Word too old to read
        # the first. Only one is ever shown, and only one may be read.
        document = docx.Document()
        document.add_paragraph("Body")
        footer = document.sections[0].footer
        footer.is_linked_to_previous = False
        run_xml = f"""
        <w:r {nsdecls("w")}
             xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
          <mc:AlternateContent>
            <mc:Choice Requires="wps">
              <w:pict><w:txbxContent>
                <w:p><w:r><w:t>Choice text</w:t></w:r></w:p>
              </w:txbxContent></w:pict>
            </mc:Choice>
            <mc:Fallback>
              <w:pict><w:txbxContent>
                <w:p><w:r><w:t>Fallback text</w:t></w:r></w:p>
              </w:txbxContent></w:pict>
            </mc:Fallback>
          </mc:AlternateContent>
        </w:r>
        """
        footer.paragraphs[0]._p.append(parse_xml(run_xml))
        path = tmp_path / "brief.docx"
        document.save(str(path))
        texts = [block.text() for block in load_footer(path)]  # type: ignore[union-attr]
        assert "Choice text" in texts
        assert "Fallback text" not in texts


def _top_level_runs(blocks: list[RichBlock]) -> list[RichRun]:
    return [run for block in blocks if isinstance(block, RichParagraph) for run in block.runs]


class TestImages:
    """A picture in a source document -- typically a photo in an identity
    table cell, as in the real ``cv-head.docx`` -- is read into the run that
    carries it, not silently dropped the way a text-only run reader would drop
    it (a picture-only run's ``text`` is empty). ``add_picture`` writes an
    inline picture (``wp:inline``); a floating one (``wp:anchor``, what
    ``cv-head.docx`` actually uses) wraps the same ``pic:pic`` differently, but
    ``_run_image`` finds the ``a:blip`` either way without caring which."""

    def test_an_inline_image_is_read(self, tmp_path: Path) -> None:
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image_runs = [r for r in _top_level_runs(blocks) if r.image is not None]
        assert len(image_runs) == 1
        assert image_runs[0].image is not None
        assert image_runs[0].image.media_type == "image/png"

    def test_an_image_run_with_no_text_is_not_dropped(self, tmp_path: Path) -> None:
        # A picture-only run has empty `.text`; only a text-blind filter would
        # mistake that for an empty, droppable run.
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("Before. ")
        picture_run = paragraph.add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        paragraph.add_run(" After.")
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        found = [r for r in _top_level_runs(blocks) if r.image is not None]
        assert len(found) == 1

    def test_image_bytes_round_trip(self, tmp_path: Path) -> None:
        data = png(20, 20)
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(data))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image_runs = [r for r in _top_level_runs(blocks) if r.image is not None]
        assert image_runs[0].image is not None
        assert image_runs[0].image.data == data

    def test_an_image_in_a_table_cell_is_read(self, tmp_path: Path) -> None:
        # The real layout: identity text in one cell, a photo in the next.
        document = docx.Document()
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].paragraphs[0].add_run("Ada Lovelace")
        run = table.rows[0].cells[1].paragraphs[0].add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert any(r.image is not None for r in runs(blocks))

    def test_an_image_run_is_not_merged_with_a_neighbouring_text_run(self, tmp_path: Path) -> None:
        # Merging equally-formatted neighbours (see TestFormatting) must not
        # concatenate a picture run's (empty) text onto a plain one and lose
        # the picture in the process.
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("Before")
        picture_run = paragraph.add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        paragraph_runs = _top_level_runs(blocks)
        assert any(r.image is not None for r in paragraph_runs)
        assert any(r.text == "Before" for r in paragraph_runs)

    def test_a_resized_image_keeps_its_displayed_size(self, tmp_path: Path) -> None:
        # `png(20, 20)` is a 20x20-pixel bitmap; asking for a 3cm x 4cm display
        # size is the case this exists for -- a photo embedded at full camera
        # resolution but shown much smaller in the source document.
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)), width=Cm(3), height=Cm(4))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image_runs = [r for r in _top_level_runs(blocks) if r.image is not None]
        assert image_runs[0].image is not None
        assert image_runs[0].image.width_emu == Cm(3)
        assert image_runs[0].image.height_emu == Cm(4)

    def test_an_unsized_image_still_gets_the_size_word_wrote(self, tmp_path: Path) -> None:
        # `add_picture` with no explicit width/height still writes a `wp:extent`
        # of its own (the bitmap's native size at 96dpi) -- read that one too,
        # rather than treating "no size given to add_picture" as "no size to read".
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image_runs = [r for r in _top_level_runs(blocks) if r.image is not None]
        image = image_runs[0].image
        assert image is not None
        assert image.width_emu is not None
        assert image.height_emu is not None

    def test_a_picture_anchored_behind_the_text_is_not_imported(self, tmp_path: Path) -> None:
        # A letterhead-style header commonly floats a full-page background
        # image behind the text (`wp:anchor behindDoc="1"`) -- Word shows it
        # as page scenery. Importing it like any other picture would flatten
        # it into an inline image the size of a full page, pushing real
        # content onto a spurious extra page.
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("Before")
        picture_run = paragraph.add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        drawing = picture_run._r.find(qn("w:drawing"))
        inline = drawing.find(qn("wp:inline"))
        inline.tag = qn("wp:anchor")
        inline.set("behindDoc", "1")
        inline.set("simplePos", "0")
        inline.find(qn("wp:extent")).set("cx", str(Cm(21)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        paragraph_runs = _top_level_runs(blocks)
        assert not any(r.image is not None for r in paragraph_runs)
        assert any(r.text == "Before" for r in paragraph_runs)

    def test_a_small_picture_behind_the_text_is_still_imported(self, tmp_path: Path) -> None:
        # A CV portrait placed into a table cell is routinely anchored behind
        # the text too, so the cell's text does not reflow around it -- that
        # one is content, not page scenery.
        document = docx.Document()
        picture_run = document.add_paragraph().add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)), width=Cm(4.6))
        inline = picture_run._r.find(qn("w:drawing")).find(qn("wp:inline"))
        inline.tag = qn("wp:anchor")
        inline.set("behindDoc", "1")
        inline.set("simplePos", "0")
        path = tmp_path / "portrait.docx"
        document.save(str(path))

        blocks = load_section(path)
        assert any(r.image is not None for r in _top_level_runs(blocks))


class TestImageCrop:
    """``a:srcRect`` -- Word's own crop record -- becomes ``Photo``'s
    ``crop_left``/``crop_top``/``crop_right``/``crop_bottom``, each a fraction
    (0..1) of the picture (see ``_crop_fractions``)."""

    def test_a_cropped_picture_keeps_its_crop_fractions(self, tmp_path: Path) -> None:
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        blip = run._r.find(f".//{qn('a:blip')}")
        src_rect = parse_xml(f'<a:srcRect {nsdecls("a")} l="10000" t="20000" r="5000" b="25000"/>')
        blip.addnext(src_rect)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image = next(r for r in _top_level_runs(blocks) if r.image is not None).image
        assert image is not None
        assert image.crop_left == pytest.approx(0.1)
        assert image.crop_top == pytest.approx(0.2)
        assert image.crop_right == pytest.approx(0.05)
        assert image.crop_bottom == pytest.approx(0.25)

    def test_an_edge_missing_from_src_rect_crops_nothing_on_that_edge(self, tmp_path: Path) -> None:
        # `a:srcRect`'s own edges are each individually optional -- a picture
        # cropped on only one side has no `l`/`t`/`b` at all, not zeros.
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        blip = run._r.find(f".//{qn('a:blip')}")
        src_rect = parse_xml(f'<a:srcRect {nsdecls("a")} r="30000"/>')
        blip.addnext(src_rect)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image = next(r for r in _top_level_runs(blocks) if r.image is not None).image
        assert image is not None
        assert (image.crop_left, image.crop_top, image.crop_bottom) == (0.0, 0.0, 0.0)
        assert image.crop_right == pytest.approx(0.3)

    def test_an_uncropped_picture_has_zero_crop_fractions(self, tmp_path: Path) -> None:
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image = next(r for r in _top_level_runs(blocks) if r.image is not None).image
        assert image is not None
        assert (image.crop_left, image.crop_top, image.crop_right, image.crop_bottom) == (
            0.0,
            0.0,
            0.0,
            0.0,
        )


def _anchor(picture_run: Run) -> BaseOxmlElement:
    """Retag `picture_run`'s inline picture as a floating one, for a test.

    Only what `_float_side` itself reads -- `behindDoc`/`simplePos` (also set
    by a real anchor, kept here so this stays a plausible one) plus whatever
    wrap/position the test appends -- not a schema-complete `wp:anchor`, the
    same "just enough to exercise the importer" as `write_projektliste`'s
    fixture is for a section import.
    """
    drawing = picture_run._r.find(qn("w:drawing"))
    inline = cast(BaseOxmlElement, drawing.find(qn("wp:inline")))
    inline.tag = qn("wp:anchor")
    inline.set("behindDoc", "0")
    inline.set("simplePos", "0")
    return inline


class TestFloatingImagePosition:
    """A floating picture (``wp:anchor``) Word wraps text around, and
    positions with a plain left/right keyword, keeps that side
    (``RichRun.float_side`` -- see ``_float_side``). Every other floating
    shape is flattened into the reading order in place, ``float_side`` left
    ``None`` -- the same as before this existed."""

    def test_wrapped_square_and_aligned_left_keeps_left(self, tmp_path: Path) -> None:
        document = docx.Document()
        picture_run = document.add_paragraph().add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        anchor = _anchor(picture_run)
        anchor.append(parse_xml(f'<wp:wrapSquare {nsdecls("wp")} wrapText="bothSides"/>'))
        position_h = parse_xml(f'<wp:positionH {nsdecls("wp")} relativeFrom="column"/>')
        position_h.append(parse_xml(f"<wp:align {nsdecls('wp')}>left</wp:align>"))
        anchor.append(position_h)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        run = next(r for r in _top_level_runs(blocks) if r.image is not None)
        assert run.float_side == "left"

    def test_wrapped_tight_and_aligned_right_keeps_right(self, tmp_path: Path) -> None:
        document = docx.Document()
        picture_run = document.add_paragraph().add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        anchor = _anchor(picture_run)
        anchor.append(parse_xml(f'<wp:wrapTight {nsdecls("wp")} wrapText="bothSides"/>'))
        position_h = parse_xml(f'<wp:positionH {nsdecls("wp")} relativeFrom="column"/>')
        position_h.append(parse_xml(f"<wp:align {nsdecls('wp')}>right</wp:align>"))
        anchor.append(position_h)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        run = next(r for r in _top_level_runs(blocks) if r.image is not None)
        assert run.float_side == "right"

    def test_wrap_none_has_no_float_side(self, tmp_path: Path) -> None:
        # `wrapNone` (or `wrapTopAndBottom`) leaves no text beside the picture
        # to wrap -- nothing for "left"/"right" to mean.
        document = docx.Document()
        picture_run = document.add_paragraph().add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        anchor = _anchor(picture_run)
        anchor.append(parse_xml(f"<wp:wrapNone {nsdecls('wp')}/>"))
        position_h = parse_xml(f'<wp:positionH {nsdecls("wp")} relativeFrom="column"/>')
        position_h.append(parse_xml(f"<wp:align {nsdecls('wp')}>left</wp:align>"))
        anchor.append(position_h)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        run = next(r for r in _top_level_runs(blocks) if r.image is not None)
        assert run.float_side is None

    def test_positioned_by_offset_has_no_float_side(self, tmp_path: Path) -> None:
        # `wp:posOffset` is measured against the source's own column width and
        # margins, which this project does not carry over -- see the module
        # docstring -- so there is no side to translate it into here.
        document = docx.Document()
        picture_run = document.add_paragraph().add_run()
        picture_run.add_picture(io.BytesIO(png(20, 20)))
        anchor = _anchor(picture_run)
        anchor.append(parse_xml(f'<wp:wrapSquare {nsdecls("wp")} wrapText="bothSides"/>'))
        position_h = parse_xml(f'<wp:positionH {nsdecls("wp")} relativeFrom="column"/>')
        position_h.append(parse_xml(f"<wp:posOffset {nsdecls('wp')}>914400</wp:posOffset>"))
        anchor.append(position_h)
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        run = next(r for r in _top_level_runs(blocks) if r.image is not None)
        assert run.float_side is None

    def test_an_inline_picture_has_no_float_side(self, tmp_path: Path) -> None:
        document = docx.Document()
        run = document.add_paragraph().add_run()
        run.add_picture(io.BytesIO(png(20, 20)))
        path = tmp_path / "brief.docx"
        document.save(str(path))

        blocks = load_section(path)
        image_run = next(r for r in _top_level_runs(blocks) if r.image is not None)
        assert image_run.float_side is None
