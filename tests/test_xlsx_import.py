"""Tests for reading a cell rectangle out of an existing `.xlsx`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.errors import CVParseError
from cv_generator.models import RichTable
from cv_generator.xlsx_import import load_section
from tests.support import (
    AFTER_RECTANGLE,
    BEFORE_RECTANGLE,
    WORKBOOK_HEADERS,
    write_workbook,
)


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    return write_workbook(tmp_path / "Rechnung.xlsx")


@pytest.fixture
def table(workbook: Path) -> RichTable:
    blocks = load_section(workbook, col_start="C", col_end="G", row_start=3, row_end=5)
    assert len(blocks) == 1
    assert isinstance(blocks[0], RichTable)
    return blocks[0]


def texts(table: RichTable) -> list[list[str]]:
    return [[cell.paragraphs[0].text() for cell in row] for row in table.rows]


class TestRectangle:
    def test_one_table_for_the_whole_rectangle(self, table: RichTable) -> None:
        # Three rows (3, 4, 5), five columns (C-G) -- unlike a `.docx` import,
        # a blank row inside the rectangle is part of the grid, not spacing.
        assert [len(row) for row in table.rows] == [5, 5, 5]

    def test_cells_are_read_left_to_right_top_to_bottom(self, table: RichTable) -> None:
        assert texts(table)[0] == list(WORKBOOK_HEADERS)

    def test_the_table_is_centered(self, table: RichTable) -> None:
        # Unlike a `.docx` import, a spreadsheet range is not meant to fill the
        # page -- it reads as a figure dropped into the document.
        assert table.centered is True

    def test_content_outside_the_rectangle_is_not_imported(self, table: RichTable) -> None:
        flat = [text for row in texts(table) for text in row]
        assert BEFORE_RECTANGLE not in flat
        assert AFTER_RECTANGLE not in flat

    def test_an_empty_cell_is_an_empty_paragraph(self, table: RichTable) -> None:
        blank = table.rows[1][0]
        assert len(blank.paragraphs) == 1
        assert blank.paragraphs[0].runs == []

    def test_columns_are_matched_case_insensitively(self, workbook: Path) -> None:
        blocks = load_section(workbook, col_start="c", col_end="g", row_start=3, row_end=3)
        assert isinstance(blocks[0], RichTable)
        assert len(blocks[0].rows[0]) == 5

    def test_col_start_after_col_end_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(CVParseError, match="'col-start' 'G' comes after 'col-end' 'C'"):
            load_section(workbook, col_start="G", col_end="C", row_start=3, row_end=3)

    def test_row_start_after_row_end_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(CVParseError, match="'row-start' 5 comes after 'row-end' 3"):
            load_section(workbook, col_start="C", col_end="G", row_start=5, row_end=3)

    def test_row_start_below_one_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(CVParseError, match="'row-start' must be at least 1"):
            load_section(workbook, col_start="C", col_end="G", row_start=0, row_end=3)

    def test_not_a_column_letter_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(CVParseError, match="not a column letter"):
            load_section(workbook, col_start="1", col_end="G", row_start=3, row_end=3)

    def test_a_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="cannot read"):
            load_section(tmp_path / "gone.xlsx", col_start="C", col_end="G", row_start=3, row_end=3)

    def test_a_file_that_is_not_an_excel_workbook(self, tmp_path: Path) -> None:
        path = tmp_path / "Rechnung.xlsx"
        path.write_text("just text", encoding="utf-8")
        with pytest.raises(CVParseError, match="as an Excel workbook"):
            load_section(path, col_start="C", col_end="G", row_start=3, row_end=3)


class TestFormatting:
    def test_the_header_row_is_bold_at_its_own_size(self, table: RichTable) -> None:
        header_runs = [cell.paragraphs[0].runs[0] for cell in table.rows[0]]
        assert all(run.bold for run in header_runs)
        assert all(run.size_pt == 14.0 for run in header_runs)

    def test_a_date_cell_is_rendered_day_month_year(self, table: RichTable) -> None:
        assert texts(table)[2][0] == "21.08.2026"

    def test_a_currency_cell_gets_its_symbol_and_thousands_grouping(self, table: RichTable) -> None:
        assert texts(table)[2][2] == "150,00 €"

    def test_a_plain_number_is_rendered_without_the_currency_format(self, table: RichTable) -> None:
        assert texts(table)[2][1] == "8.5"

    def test_a_ruled_range_says_so(self, table: RichTable) -> None:
        assert table.bordered is True

    def test_a_range_without_any_border_is_not_ruled(self, workbook: Path) -> None:
        blocks = load_section(workbook, col_start="C", col_end="G", row_start=5, row_end=5)
        assert isinstance(blocks[0], RichTable)
        assert blocks[0].bordered is False


class TestGeometry:
    def test_column_widths_are_the_sheet_s_own_proportions(self, table: RichTable) -> None:
        assert table.column_widths
        assert sum(table.column_widths) == pytest.approx(1.0)
        assert len(table.column_widths) == 5
