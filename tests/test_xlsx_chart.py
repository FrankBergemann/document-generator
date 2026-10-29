"""Tests for importing a chart out of an existing `.xlsx` as a picture."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from cv_generator.errors import DocParseError
from cv_generator.models import RichParagraph
from cv_generator.xlsx_chart import (
    CHART_HEIGHT_MM,
    CHART_WIDTH_MM,
    Chart,
    load_diagram,
    read_diagram,
)
from tests.support import (
    CHART_COUNTS,
    CHART_MONTHS,
    CHART_REVENUE,
    CHART_SHEET,
    CHART_TITLE,
    TREND_SHEET,
    TREND_TITLE,
    write_chart_workbook,
)

EMU_PER_MM = 36000


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    return write_chart_workbook(tmp_path / "Umsatz.xlsx")


@pytest.fixture
def chart(workbook: Path) -> Chart:
    return read_diagram(workbook, diagram=CHART_TITLE, tab=CHART_SHEET)


class TestFindingTheChart:
    def test_the_chart_is_found_by_its_title(self, chart: Chart) -> None:
        assert chart.title == CHART_TITLE

    def test_the_title_is_matched_case_insensitively_as_a_pattern(self, workbook: Path) -> None:
        found = read_diagram(workbook, diagram="stückzahl und .* je monat", tab=CHART_SHEET)
        assert found.title == CHART_TITLE

    def test_a_partial_title_does_not_match(self, workbook: Path) -> None:
        # `fullmatch`, like `begin`/`end`: "Umsatz" must not find
        # "Stückzahl und Umsatz je Monat".
        with pytest.raises(DocParseError, match="no chart on sheet 'Umsatz' is titled 'Umsatz'"):
            read_diagram(workbook, diagram="Umsatz", tab=CHART_SHEET)

    def test_without_a_tab_the_active_sheet_is_searched(self, workbook: Path) -> None:
        assert read_diagram(workbook, diagram=CHART_TITLE).title == CHART_TITLE

    def test_the_tab_decides_which_sheet_is_searched(self, workbook: Path) -> None:
        assert read_diagram(workbook, diagram=TREND_TITLE, tab=TREND_SHEET).title == TREND_TITLE
        with pytest.raises(DocParseError, match="no chart on sheet 'Umsatz'"):
            read_diagram(workbook, diagram=TREND_TITLE, tab=CHART_SHEET)

    def test_an_unknown_tab_is_an_error_naming_the_sheets(self, workbook: Path) -> None:
        with pytest.raises(
            DocParseError, match="no sheet named 'Nope' \\(sheets: 'Umsatz', 'Trend'\\)"
        ):
            read_diagram(workbook, diagram=CHART_TITLE, tab="Nope")

    def test_no_match_names_the_charts_that_are_there(self, workbook: Path) -> None:
        with pytest.raises(DocParseError, match=f"found: '{CHART_TITLE}', 'Chart"):
            read_diagram(workbook, diagram="Gewinn", tab=CHART_SHEET)

    def test_an_untitled_chart_is_matched_by_its_object_name(self, workbook: Path) -> None:
        found = read_diagram(workbook, diagram="Chart \\d+", tab=CHART_SHEET)
        assert found.title is None

    def test_a_pattern_matching_several_charts_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(DocParseError, match="2 charts on sheet 'Umsatz' match"):
            read_diagram(workbook, diagram=".*", tab=CHART_SHEET)

    def test_an_invalid_pattern_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(DocParseError, match="not a valid regular expression"):
            read_diagram(workbook, diagram="(", tab=CHART_SHEET)

    def test_an_unsupported_chart_type_is_an_error(self, workbook: Path) -> None:
        with pytest.raises(DocParseError, match="chart type 'areaChart' is not supported"):
            read_diagram(workbook, diagram="Fläche", tab=TREND_SHEET)

    def test_a_file_that_is_no_workbook_is_an_error(self, tmp_path: Path) -> None:
        bogus = tmp_path / "bogus.xlsx"
        bogus.write_text("not a zip")
        with pytest.raises(DocParseError, match=r"cannot read .* as an Excel workbook"):
            read_diagram(bogus, diagram=CHART_TITLE)


class TestReadingTheChart:
    def test_both_plot_groups_are_bar_plots_on_their_own_value_axes(self, chart: Chart) -> None:
        assert [plot.kind for plot in chart.plots] == ["bar", "bar"]
        assert chart.plots[0].value_axis != chart.plots[1].value_axis
        assert chart.plots[0].category_axis == chart.plots[1].category_axis

    def test_series_are_named_and_valued_from_the_cells(self, chart: Chart) -> None:
        # openpyxl writes no cached points, so these come from the sheet itself.
        counts = chart.plots[0].series[0]
        revenue = chart.plots[1].series[1]
        assert (counts.name, counts.values) == ("Stück", list(CHART_COUNTS))
        assert (revenue.name, revenue.values) == ("Umsatz", list(CHART_REVENUE))
        assert counts.categories == list(CHART_MONTHS)

    def test_a_spacer_series_keeps_its_slot_but_draws_nothing(self, chart: Chart) -> None:
        # The side-by-side trick: an unfilled, empty series after the count
        # and before the revenue, so each takes one half of the group.
        assert [len(plot.series) for plot in chart.plots] == [2, 2]
        assert chart.plots[0].series[1].color == "none"
        assert chart.plots[1].series[0].color == "none"
        assert chart.plots[1].series[0].name is None

    def test_axis_titles_and_number_format_are_read(self, chart: Chart) -> None:
        count_axis = chart.axes[chart.plots[0].value_axis or ""]
        revenue_axis = chart.axes[chart.plots[1].value_axis or ""]
        assert count_axis.title == "Stück"
        assert revenue_axis.title == "Umsatz"
        assert revenue_axis.number_format == "#,##0.00"
        assert count_axis.gridlines is True
        assert revenue_axis.gridlines is False

    def test_a_line_chart_is_read_as_one(self, workbook: Path) -> None:
        trend = read_diagram(workbook, diagram=TREND_TITLE, tab=TREND_SHEET)
        assert [plot.kind for plot in trend.plots] == ["line"]
        assert trend.plots[0].series[0].values == list(CHART_REVENUE)


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">2I", data[16:24])
    return width, height


class TestThePicture:
    @pytest.fixture
    def paragraph(self, workbook: Path) -> RichParagraph:
        blocks = load_diagram(workbook, diagram=CHART_TITLE, tab=CHART_SHEET)
        assert len(blocks) == 1
        assert isinstance(blocks[0], RichParagraph)
        return blocks[0]

    def test_one_centered_paragraph_holding_one_picture(self, paragraph: RichParagraph) -> None:
        assert paragraph.alignment == "center"
        assert len(paragraph.runs) == 1
        assert paragraph.runs[0].image is not None
        assert paragraph.runs[0].text == ""

    def test_the_picture_is_a_png_at_print_resolution(self, paragraph: RichParagraph) -> None:
        image = paragraph.runs[0].image
        assert image is not None
        assert image.media_type == "image/png"
        width, height = png_size(image.data)
        # 200 dpi: well above what a printed page needs.
        assert width == pytest.approx(CHART_WIDTH_MM / 25.4 * 200, abs=2)
        assert height == pytest.approx(CHART_HEIGHT_MM / 25.4 * 200, abs=2)

    def test_the_display_size_is_the_page_s_content_width(self, paragraph: RichParagraph) -> None:
        image = paragraph.runs[0].image
        assert image is not None
        assert image.width_emu == CHART_WIDTH_MM * EMU_PER_MM
        assert image.height_emu == CHART_HEIGHT_MM * EMU_PER_MM

    def test_a_line_chart_draws_too(self, workbook: Path) -> None:
        blocks = load_diagram(workbook, diagram=TREND_TITLE, tab=TREND_SHEET)
        assert isinstance(blocks[0], RichParagraph)
        assert blocks[0].runs[0].image is not None
