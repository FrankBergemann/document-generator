from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.docx_import import load_section
from cv_generator.errors import CVParseError
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

    def test_an_end_that_never_comes_is_an_error(self, projektliste: Path) -> None:
        # Not "run to the end of the document": the recipe said where to stop,
        # so importing the rest would put another section's content in this one.
        with pytest.raises(CVParseError, match="no heading 'Publikationen' follows"):
            load_section(projektliste, "Projekthistorie", "Publikationen")

    def test_an_end_before_the_beginning_does_not_count(self, projektliste: Path) -> None:
        with pytest.raises(CVParseError, match="no heading 'Profil' follows"):
            load_section(projektliste, "Projekthistorie", "Profil")


class TestSectionBoundaries:
    def test_one_block_per_project(self, blocks: list[RichBlock]) -> None:
        # The blank paragraphs Word needs between two tables are not content.
        assert len(blocks) == len(SAMPLE_PROJECTS)
        assert len(tables(blocks)) == len(SAMPLE_PROJECTS)

    def test_earlier_sections_are_not_imported(self, blocks: list[RichBlock]) -> None:
        assert BEFORE_HEADING not in texts(blocks)

    def test_import_stops_at_the_next_heading(self, blocks: list[RichBlock]) -> None:
        assert AFTER_SECTION not in texts(blocks)

    def test_heading_is_matched_case_insensitively(self, projektliste: Path) -> None:
        assert load_section(projektliste, "projekthistorie")

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
        with pytest.raises(CVParseError, match="no heading 'Projekte' found"):
            load_section(projektliste, "Projekte")

    def test_empty_section_is_an_error(self, tmp_path: Path) -> None:
        path = write_projektliste(tmp_path / PROJEKTLISTE_NAME, [])
        with pytest.raises(CVParseError, match="nothing follows the heading"):
            load_section(path, "Projekthistorie")

    def test_a_file_that_is_not_a_word_document(self, tmp_path: Path) -> None:
        path = tmp_path / "Projektliste.docx"
        path.write_text("just text", encoding="utf-8")
        with pytest.raises(CVParseError, match="as a Word document"):
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
