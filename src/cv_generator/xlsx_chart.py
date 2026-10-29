"""Read one chart out of an existing ``.xlsx`` and into the Document model, as a picture.

A workbook's chart is often the one thing worth showing from it -- a summary
someone already drew, over data nobody wants to retype. An ``"xlsx"`` entry
naming a ``diagram`` (and, usually, the ``tab`` it sits on) imports that chart
instead of a cell rectangle; see :class:`cv_generator.config.SectionSpec`.

A chart is *data plus drawing instructions*, not a picture: Excel draws it
afresh every time the file is opened, and the ``.xlsx`` holds no rendered image
of it. So this module does two separate things:

* **Read** the chart's DrawingML (``xl/charts/chartN.xml``) into a small,
  renderer-free description -- :class:`Chart` and friends, which
  :func:`read_diagram` returns. openpyxl cannot
  help here: it discards every chart when it loads a workbook. The chart is
  found the way Excel itself finds it: sheet name -> worksheet part -> its
  drawing part -> each graphic frame's chart part, following the package
  relationships at every step.
* **Draw** that description with matplotlib into a PNG (:func:`draw`), carried as a
  :class:`~cv_generator.models.Photo` in a single, centered image run. A
  picture is the one form every backend already renders identically (an
  ``<img>`` in HTML and so in the PDF, an embedded picture in ``.docx``), so a
  chart needs no backend changes and cannot look different in one output
  format than in another.

What "keeping the chart" means here:

* **Carried over** -- the title, the series with their names and literal
  (``srgbClr``) colours, which value axis each plot group belongs to (a
  secondary axis on the right is common for a second unit, e.g. revenue next to
  a count), axis titles, the value axes' number format, major gridlines,
  category-label rotation, the legend's position and the entries it deletes,
  and a clustered bar chart's exact slot layout. The last one matters more than
  it looks: a common Excel trick puts two bar series on two axes side by side by
  adding *invisible* spacer series (``a:noFill``, no values) to each group.
  Laying out every series' slot, drawn or not, reproduces that without
  recognising the trick as such.
* **Supported chart types** -- bar/column (clustered, stacked, percent-stacked),
  line and pie. Anything else is a :class:`~cv_generator.errors.DocParseError`
  naming the type, not a blank picture.
* **Values are the cached ones**, the same ``data_only`` reading the cell-range
  import does: Excel stores each series' last values next to its formula
  (``c:numCache``/``c:strCache``). Only a series with no cache at all -- a
  workbook written by a library rather than by Excel -- has its formula
  resolved against the sheet's own (cached) cell values instead.
* **Decided here, not taken from the workbook** -- the font (matplotlib's own
  sans-serif), theme colours (``schemeClr`` maps to Office's default accent
  palette rather than the workbook's ``theme1.xml``, the same limit
  :mod:`cv_generator.xlsx_import` accepts for font colour), and the chart's
  size, which is fitted to the page's content width rather than taken from its
  cell anchor.
"""

from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.exceptions import InvalidFileException

from cv_generator.errors import DocParseError
from cv_generator.models import Photo, RichBlock, RichParagraph, RichRun

if TYPE_CHECKING:
    from matplotlib.artist import Artist
    from matplotlib.axes import Axes
    from matplotlib.axis import Axis as Ruler
    from matplotlib.figure import Figure

_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}
_R_ID = f"{{{_NS['r']}}}id"
_REL_DRAWING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"

# Office's default accent colours, accent1..accent6 -- what a series with no
# colour of its own, or one naming a theme accent (`schemeClr`), is drawn in.
_OFFICE_ACCENTS = ("#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47")

# DrawingML angles are in 60000ths of a degree, font sizes in 100ths of a point.
_ANGLE_UNIT = 60000
_SIZE_UNIT = 100
_EMU_PER_MM = 36000

# The picture's display size: the page's content width (A4 less 15mm margins,
# `WordTheme.content_width_mm`) at 16:10, close to Excel's own default chart
# shape. Rendered at print resolution, since a PDF is usually the point.
CHART_WIDTH_MM = 180.0
CHART_HEIGHT_MM = 112.5
_DPI = 200

_PlotKind = Literal["bar", "line", "pie"]
_PLOT_KINDS: dict[str, _PlotKind] = {"barChart": "bar", "lineChart": "line", "pieChart": "pie"}

# A legend entry: the series' place in the chart (`c:order`), what is drawn
# for it, and its label.
_Handle = tuple[int, "Artist", str]

_OutsideLocation = Literal["outside lower center", "outside left upper", "outside right upper"]
_LEGEND_LOCATIONS: dict[str, _OutsideLocation] = {
    "b": "outside lower center",
    "l": "outside left upper",
}


# -- the chart, read -----------------------------------------------------------


@dataclass
class Series:
    # `c:order` -- the series' place in its plot and in the legend. (`c:idx`
    # only picks its default colour.)
    order: int
    name: str | None
    categories: list[str]
    values: list[float | None]
    # A hex colour, or "none" for an explicit `a:noFill`: a spacer, drawn as
    # nothing but still taking its slot in a clustered bar group.
    color: str
    # The formulas behind name, categories and values -- only read when a
    # series has no cached points (see `_fill_from_cells`).
    name_ref: str | None = None
    categories_ref: str | None = None
    values_ref: str | None = None

    def needs_cells(self) -> bool:
        return (
            (self.name is None and self.name_ref is not None)
            or (not self.categories and self.categories_ref is not None)
            or (not self.values and self.values_ref is not None)
        )


@dataclass
class Plot:
    kind: _PlotKind
    series: list[Series]
    # DrawingML lists a plot's category axis first, its value axis second; a
    # pie has neither.
    category_axis: str | None
    value_axis: str | None
    horizontal: bool = False
    grouping: str = "clustered"
    gap_width: float = 150.0


@dataclass
class Axis:
    title: str | None = None
    deleted: bool = False
    position: str = "l"
    number_format: str = "General"
    gridlines: bool = False
    # Degrees, counter-clockwise -- matplotlib's convention, not DrawingML's.
    label_rotation: float = 0.0
    title_size_pt: float | None = None
    label_size_pt: float | None = None


@dataclass
class Chart:
    title: str | None
    title_size_pt: float | None
    plots: list[Plot]
    axes: dict[str, Axis]
    # `c:legendPos` ("t", "b", "l", "r", "tr"), or None for no legend at all.
    legend_position: str | None
    # Legend entries the chart deletes, by series order.
    hidden_legend_entries: set[int] = field(default_factory=set)


def load_diagram(path: Path, *, diagram: str, tab: str | None = None) -> list[RichBlock]:
    """Import the chart titled ``diagram`` from sheet ``tab`` as one centered picture.

    See :func:`read_diagram` for how the chart is found and what can go wrong.

    Returns:
        A single-element list holding one centered :class:`RichParagraph`
        whose one run carries the chart as a PNG, sized to the page's content
        width (:data:`CHART_WIDTH_MM` by :data:`CHART_HEIGHT_MM`).
    """
    image = Photo(
        data=draw(read_diagram(path, diagram=diagram, tab=tab)),
        media_type="image/png",
        width_emu=round(CHART_WIDTH_MM * _EMU_PER_MM),
        height_emu=round(CHART_HEIGHT_MM * _EMU_PER_MM),
    )
    return [RichParagraph(runs=[RichRun(text="", image=image)], alignment="center")]


def read_diagram(path: Path, *, diagram: str, tab: str | None = None) -> Chart:
    """Find the chart titled ``diagram`` on sheet ``tab`` and read what it shows.

    Args:
        diagram: A regular expression, matched case-insensitively against the
            *whole* chart title -- the same rule ``begin``/``end`` follow, so
            plain text matches exactly the one chart it names. A chart without
            a title of its own is matched by its drawing object's name instead
            (Excel's "Chart 1", or whatever the selection pane renamed it to).
        tab: The sheet the chart is placed on. ``None`` means the workbook's
            active sheet, the same default the cell-rectangle import uses.

    Raises:
        DocParseError: if the workbook cannot be read, ``tab`` names no sheet,
            ``diagram`` is not a valid pattern or matches no chart or several,
            or the chart is of a type this module does not draw.
    """
    pattern = _compile_title(diagram, path=path)
    with _open(path) as package:
        sheet_name, sheet_part = _sheet_part(package, path, tab)
        candidates = _charts_on(package, sheet_part)
        matches = [part for label, part in candidates if pattern.fullmatch(label.strip())]
        if not matches:
            found = ", ".join(repr(label) for label, _ in candidates) or "none"
            raise DocParseError(
                f"{path}: no chart on sheet {sheet_name!r} is titled {diagram!r} (found: {found})"
            )
        if len(matches) > 1:
            raise DocParseError(
                f"{path}: {len(matches)} charts on sheet {sheet_name!r} match {diagram!r}; "
                "make the pattern name exactly one"
            )
        chart = _read_chart(package, path, matches[0])

    if any(series.needs_cells() for plot in chart.plots for series in plot.series):
        _fill_from_cells(path, chart)
    return chart


def _compile_title(text: str, *, path: Path) -> re.Pattern[str]:
    try:
        return re.compile(text.strip(), re.IGNORECASE)
    except re.error as exc:
        raise DocParseError(f"{path}: {text!r} is not a valid regular expression: {exc}") from exc


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocParseError(f"cannot read {path} as an Excel workbook: {exc}") from exc


# -- finding the chart's part --------------------------------------------------


def _xml(package: zipfile.ZipFile, part: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(package.read(part))
    except (KeyError, ElementTree.ParseError) as exc:
        raise DocParseError(f"{package.filename}: cannot read part {part!r}: {exc}") from exc


def _relationships(package: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """A part's relationships, as ``{id: (type, target part)}``."""
    folder, name = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels_part not in package.namelist():
        return {}
    relationships = {}
    for rel in _xml(package, rels_part).iterfind("rel:Relationship", _NS):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        # A target is relative to the part's own folder, unless it is absolute
        # within the package.
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.join(folder, target)
        relationships[rel.get("Id", "")] = (rel.get("Type", ""), posixpath.normpath(resolved))
    return relationships


def _sheet_part(package: zipfile.ZipFile, path: Path, tab: str | None) -> tuple[str, str]:
    """The name and part of sheet ``tab``, or of the active sheet when it is None."""
    workbook = _xml(package, "xl/workbook.xml")
    sheets = [
        (sheet.get("name", ""), sheet.get(_R_ID, ""))
        for sheet in workbook.iterfind("main:sheets/main:sheet", _NS)
    ]
    if not sheets:
        raise DocParseError(f"{path}: the workbook has no sheets")
    if tab is None:
        view = workbook.find("main:bookViews/main:workbookView", _NS)
        active = int(view.get("activeTab", "0")) if view is not None else 0
        name, rel_id = sheets[min(active, len(sheets) - 1)]
    else:
        named = [sheet for sheet in sheets if sheet[0] == tab]
        if not named:
            names = ", ".join(repr(name) for name, _ in sheets)
            raise DocParseError(f"{path}: no sheet named {tab!r} (sheets: {names})")
        name, rel_id = named[0]
    relationships = _relationships(package, "xl/workbook.xml")
    if rel_id not in relationships:
        raise DocParseError(f"{path}: sheet {name!r} has no part in the workbook")
    return name, relationships[rel_id][1]


def _charts_on(package: zipfile.ZipFile, sheet_part: str) -> list[tuple[str, str]]:
    """Every chart on a sheet, as ``(title, or else object name; chart part)``."""
    charts = []
    for kind, drawing_part in _relationships(package, sheet_part).values():
        if kind != _REL_DRAWING:
            continue
        drawing_rels = _relationships(package, drawing_part)
        for frame in _xml(package, drawing_part).iter(f"{{{_NS['xdr']}}}graphicFrame"):
            reference = frame.find(".//c:chart", _NS)
            rel_id = reference.get(_R_ID, "") if reference is not None else ""
            if rel_id not in drawing_rels:
                continue
            chart_part = drawing_rels[rel_id][1]
            title = _rich_text(_xml(package, chart_part).find("c:chart/c:title", _NS))
            if title is None:
                properties = frame.find("xdr:nvGraphicFramePr/xdr:cNvPr", _NS)
                title = properties.get("name", "") if properties is not None else ""
            charts.append((title, chart_part))
    return charts


# -- reading the chart ---------------------------------------------------------


def _val(element: ElementTree.Element | None, default: str = "") -> str:
    return element.get("val", default) if element is not None else default


def _flag(element: ElementTree.Element | None) -> bool:
    return _val(element) in ("1", "true")


def _rich_text(title: ElementTree.Element | None) -> str | None:
    if title is None:
        return None
    text = "".join(run.text or "" for run in title.iterfind("c:tx//a:t", _NS))
    return text or None


def _rich_size(container: ElementTree.Element | None) -> float | None:
    """The first explicit font size under a title or ``c:txPr``, in points."""
    if container is None:
        return None
    for element in container.iter():
        if element.tag in (f"{{{_NS['a']}}}rPr", f"{{{_NS['a']}}}defRPr") and element.get("sz"):
            return int(element.get("sz", "0")) / _SIZE_UNIT
    return None


def _read_chart(package: zipfile.ZipFile, path: Path, part: str) -> Chart:
    chart = _xml(package, part).find("c:chart", _NS)
    area = chart.find("c:plotArea", _NS) if chart is not None else None
    if chart is None or area is None:
        raise DocParseError(f"{path}: chart part {part!r} has no plot area")

    plots = []
    axes = {}
    for element in area:
        tag = element.tag.rpartition("}")[2]
        if tag.endswith("Chart"):
            kind = _PLOT_KINDS.get(tag)
            if kind is None:
                raise DocParseError(
                    f"{path}: chart type {tag!r} is not supported "
                    f"(supported: {', '.join(sorted(_PLOT_KINDS))})"
                )
            plots.append(_read_plot(element, kind))
        elif tag in ("catAx", "valAx", "dateAx"):
            axes[_val(element.find("c:axId", _NS))] = _read_axis(element)
    if not plots:
        raise DocParseError(f"{path}: chart part {part!r} has nothing plotted")

    title = chart.find("c:title", _NS)
    legend = chart.find("c:legend", _NS)
    hidden = set()
    if legend is not None:
        for entry in legend.iterfind("c:legendEntry", _NS):
            if _flag(entry.find("c:delete", _NS)):
                hidden.add(int(_val(entry.find("c:idx", _NS), "0")))
    return Chart(
        title=_rich_text(title),
        title_size_pt=_rich_size(title),
        plots=plots,
        axes=axes,
        legend_position=_val(legend.find("c:legendPos", _NS), "r") if legend is not None else None,
        hidden_legend_entries=hidden,
    )


def _read_plot(element: ElementTree.Element, kind: _PlotKind) -> Plot:
    series = sorted((_read_series(ser) for ser in element.iterfind("c:ser", _NS)), key=_order)
    axis_ids = [_val(axis) for axis in element.iterfind("c:axId", _NS)]
    return Plot(
        kind=kind,
        series=series,
        category_axis=axis_ids[0] if len(axis_ids) > 0 else None,
        value_axis=axis_ids[1] if len(axis_ids) > 1 else None,
        horizontal=_val(element.find("c:barDir", _NS)) == "bar",
        grouping=_val(element.find("c:grouping", _NS), "clustered"),
        gap_width=float(_val(element.find("c:gapWidth", _NS), "150")),
    )


def _order(series: Series) -> int:
    return series.order


def _read_series(ser: ElementTree.Element) -> Series:
    order = int(_val(ser.find("c:order", _NS), "0"))
    name = ser.find("c:tx", _NS)
    names = _points(name)
    if name is not None and not names:
        literal = name.find("c:v", _NS)  # a name typed in rather than referenced
        names = [literal.text or ""] if literal is not None else []
    categories = ser.find("c:cat", _NS)
    values = ser.find("c:val", _NS)
    return Series(
        order=order,
        name=names[0] if names else None,
        categories=_points(categories),
        values=[_number(value) for value in _points(values)],
        color=_fill(ser.find("c:spPr", _NS), int(_val(ser.find("c:idx", _NS), str(order)))),
        name_ref=_formula(name),
        categories_ref=_formula(categories),
        values_ref=_formula(values),
    )


def _formula(container: ElementTree.Element | None) -> str | None:
    formula = container.find(".//c:f", _NS) if container is not None else None
    return formula.text if formula is not None and formula.text else None


def _points(container: ElementTree.Element | None) -> list[str]:
    """A reference's (or literal's) cached points, in index order, gaps as ``""``."""
    if container is None:
        return []
    for cache in ("strCache", "numCache", "strLit", "numLit", "multiLvlStrCache"):
        found = container.find(f".//c:{cache}", _NS)
        if found is None:
            continue
        points = [""] * int(_val(found.find("c:ptCount", _NS), "0"))
        for point in found.iterfind(".//c:pt", _NS):
            index = int(point.get("idx", "0"))
            if index >= len(points):
                points.extend([""] * (index + 1 - len(points)))
            value = point.find("c:v", _NS)
            points[index] = (value.text or "") if value is not None else ""
        return points
    return []


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _fill(properties: ElementTree.Element | None, color_index: int) -> str:
    default = _OFFICE_ACCENTS[color_index % len(_OFFICE_ACCENTS)]
    if properties is None:
        return default
    if properties.find("a:noFill", _NS) is not None:
        return "none"
    # A bar's fill, else a line's stroke.
    for container in ("a:solidFill", "a:ln/a:solidFill"):
        fill = properties.find(container, _NS)
        if fill is None:
            continue
        literal = fill.find("a:srgbClr", _NS)
        if literal is not None and literal.get("val"):
            return f"#{literal.get('val')}"
        accent = re.fullmatch(r"accent([1-6])", _val(fill.find("a:schemeClr", _NS)))
        if accent:
            return _OFFICE_ACCENTS[int(accent.group(1)) - 1]
    return default


def _read_axis(element: ElementTree.Element) -> Axis:
    title = element.find("c:title", _NS)
    labels = element.find("c:txPr", _NS)
    body = labels.find("a:bodyPr", _NS) if labels is not None else None
    number_format = element.find("c:numFmt", _NS)
    return Axis(
        title=_rich_text(title),
        deleted=_flag(element.find("c:delete", _NS)),
        position=_val(element.find("c:axPos", _NS), "l"),
        number_format=(
            number_format.get("formatCode", "General") if number_format is not None else "General"
        ),
        gridlines=element.find("c:majorGridlines", _NS) is not None,
        # DrawingML turns clockwise, matplotlib counter-clockwise.
        label_rotation=-int(body.get("rot", "0")) / _ANGLE_UNIT if body is not None else 0.0,
        title_size_pt=_rich_size(title),
        label_size_pt=_rich_size(labels),
    )


def _fill_from_cells(path: Path, chart: Chart) -> None:
    """Resolve the formulas of series that have no cached points of their own."""
    try:
        workbook = load_workbook(str(path), data_only=True, read_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise DocParseError(f"cannot read {path} as an Excel workbook: {exc}") from exc

    def cells(formula: str) -> list[str]:
        sheet_name, _, reference = formula.rpartition("!")
        sheet_name = sheet_name.strip("'").replace("''", "'")
        if sheet_name not in workbook.sheetnames:
            raise DocParseError(f"{path}: a chart refers to unknown sheet {sheet_name!r}")
        min_col, min_row, max_col, max_row = range_boundaries(reference.replace("$", ""))
        rows = workbook[sheet_name].iter_rows(
            min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True
        )
        return ["" if value is None else str(value) for row in rows for value in row]

    try:
        for plot in chart.plots:
            for series in plot.series:
                if series.name is None and series.name_ref is not None:
                    series.name = next(iter(cells(series.name_ref)), None)
                if not series.categories and series.categories_ref is not None:
                    series.categories = cells(series.categories_ref)
                if not series.values and series.values_ref is not None:
                    series.values = [_number(value) for value in cells(series.values_ref)]
    finally:
        workbook.close()


# -- drawing it ----------------------------------------------------------------


def _number_formatter(code: str) -> Callable[[float, int | None], str] | None:
    """A tick formatter for an Excel number format, or None for matplotlib's own.

    Approximated the way the cell import's own number formatting is: decimal
    places, thousands grouping and a trailing ``%`` -- enough for an axis, whose
    format is usually ``0``, ``0.00`` or ``#,##0``.
    """
    if code in ("", "General"):
        return None
    section = code.split(";", 1)[0]
    percent = section.endswith("%")
    _, dot, decimals = section.rstrip("%").partition(".")
    places = sum(1 for char in decimals if char in "0#") if dot else 0
    grouping = "," if "," in section else ""

    def formatter(value: float, _position: int | None) -> str:
        text = f"{value * 100 if percent else value:{grouping}.{places}f}"
        return f"{text}%" if percent else text

    return formatter


def draw(chart: Chart) -> bytes:
    """Render ``chart`` as a PNG at print resolution."""
    # Imported here rather than at the top: matplotlib is slow to import, and a
    # build whose recipe has no diagram in it should not pay for that.
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot

    mm = 1 / 25.4
    figure = pyplot.figure(
        figsize=(CHART_WIDTH_MM * mm, CHART_HEIGHT_MM * mm), dpi=_DPI, layout="constrained"
    )
    try:
        handles: list[_Handle] = []
        if chart.plots[0].kind == "pie":
            _draw_pie(figure, chart.plots[0], handles)
        else:
            _draw_axes(figure, chart, handles)
        if chart.title:
            figure.suptitle(chart.title, fontsize=chart.title_size_pt or 14, fontweight="bold")
        _draw_legend(figure, chart, handles)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=_DPI, facecolor="white")
        return buffer.getvalue()
    finally:
        pyplot.close(figure)


def _draw_legend(figure: Figure, chart: Chart, handles: list[_Handle]) -> None:
    shown = [
        (artist, label)
        for order, artist, label in sorted(handles, key=lambda handle: handle[0])
        if order not in chart.hidden_legend_entries
    ]
    if chart.legend_position is None or not shown:
        return
    artists = [artist for artist, _ in shown]
    labels = [label for _, label in shown]
    if chart.legend_position == "t":
        # Hung from the plot rather than the figure: the constrained layout
        # does not stack a figure legend below the title, it overlaps the two.
        figure.axes[0].legend(
            artists,
            labels,
            loc="lower center",
            bbox_to_anchor=(0.5, 1.0),
            ncols=len(shown),
            frameon=False,
            fontsize=9,
        )
        return
    location = _LEGEND_LOCATIONS.get(chart.legend_position, "outside right upper")
    columns = len(shown) if chart.legend_position == "b" else 1
    figure.legend(artists, labels, loc=location, ncols=columns, frameon=False, fontsize=9)


def _draw_pie(figure: Figure, plot: Plot, handles: list[_Handle]) -> None:
    # A pie shows one series -- Excel's own rule; it ignores any further ones.
    series = next((s for s in plot.series if any(v is not None for v in s.values)), None)
    if series is None:
        return
    axes = figure.add_subplot()
    values = [value or 0.0 for value in series.values]
    colors = [_OFFICE_ACCENTS[index % len(_OFFICE_ACCENTS)] for index in range(len(values))]
    wedges, *_ = axes.pie(values, colors=colors, startangle=90, counterclock=False)
    axes.set_aspect("equal")
    for order, (wedge, label) in enumerate(zip(wedges, series.categories, strict=False)):
        handles.append((order, wedge, label))


def _draw_axes(figure: Figure, chart: Chart, handles: list[_Handle]) -> None:
    from matplotlib.ticker import FuncFormatter

    primary = figure.add_subplot()
    horizontal = chart.plots[0].horizontal
    # One matplotlib Axes per value axis: the first is the primary one, any
    # further one (a secondary axis) shares the category axis with it.
    value_axes: dict[str | None, Axes] = {}
    for plot in chart.plots:
        if plot.value_axis not in value_axes:
            twin = primary.twiny if horizontal else primary.twinx
            value_axes[plot.value_axis] = twin() if value_axes else primary
        if plot.kind == "bar":
            _draw_bars(value_axes[plot.value_axis], plot, handles)
        else:
            _draw_lines(value_axes[plot.value_axis], plot, handles)

    first = chart.plots[0]
    _style_categories(primary, chart.axes.get(first.category_axis or "", Axis()), chart)
    for axis_id, axes in value_axes.items():
        axis = chart.axes.get(axis_id or "", Axis())
        ruler: Ruler = axes.xaxis if horizontal else axes.yaxis
        if axis.deleted:
            ruler.set_visible(False)
            continue
        formatter = _number_formatter(axis.number_format)
        if formatter is not None:
            ruler.set_major_formatter(FuncFormatter(formatter))
        axes.tick_params(axis="x" if horizontal else "y", labelsize=axis.label_size_pt or 9)
        if axis.title:
            ruler.set_label_text(axis.title, fontsize=axis.title_size_pt or 10, fontweight="bold")
        if axis.gridlines:
            # Behind this Axes' own bars only: a secondary axis is a second
            # Axes on top of the first, so gridlines on *both* would cross the
            # primary bars. Excel puts them on one axis, in practice.
            axes.set_axisbelow(True)
            ruler.grid(True, color="#D9D9D9", linewidth=0.6)
    # Excel draws no box around the plot area: keep only the spines that carry
    # an axis.
    for axes in value_axes.values():
        axes.spines["top"].set_visible(False)
        if len(value_axes) == 1:
            axes.spines["right"].set_visible(False)


def _style_categories(primary: Axes, axis: Axis, chart: Chart) -> None:
    categories = next((s.categories for p in chart.plots for s in p.series if s.categories), [])
    positions = list(range(len(categories)))
    size = axis.label_size_pt or 9
    ruler: Ruler
    if chart.plots[0].horizontal:
        primary.set_yticks(positions, categories, fontsize=size, rotation=axis.label_rotation)
        primary.set_ylim(len(categories) - 0.5, -0.5)  # Excel's first category is on top
        ruler = primary.yaxis
    else:
        rotation = axis.label_rotation
        # Anchored at the end that touches the tick, so a slanted label hangs
        # from it rather than being centred across it.
        primary.set_xticks(
            positions,
            categories,
            fontsize=size,
            rotation=rotation,
            ha="right" if rotation > 0 else "left" if rotation < 0 else "center",
            rotation_mode="anchor",
        )
        primary.set_xlim(-0.5, len(categories) - 0.5)
        ruler = primary.xaxis
    if axis.deleted:
        ruler.set_visible(False)
    elif axis.title:
        ruler.set_label_text(axis.title, fontsize=axis.title_size_pt or 10, fontweight="bold")


def _draw_bars(axes: Axes, plot: Plot, handles: list[_Handle]) -> None:
    if not plot.series:
        return
    length = max(len(series.values) for series in plot.series)
    rows = [
        [math.nan if v is None else v for v in s.values] + [math.nan] * (length - len(s.values))
        for s in plot.series
    ]
    if plot.grouping == "percentStacked":
        # `rows` are all padded to `length` above, so every zip here is exact.
        totals = [
            sum(abs(v) for v in column if not math.isnan(v)) for column in zip(*rows, strict=True)
        ]
        rows = [
            [v / t * 100 if t else math.nan for v, t in zip(row, totals, strict=True)]
            for row in rows
        ]

    # Excel's layout: each category gets a band one unit wide, of which
    # `gapWidth` (a percentage of one bar group) is gap; the group is split
    # evenly between *all* the plot's series, drawn or not, unless stacked.
    group = 1 / (1 + plot.gap_width / 100)
    stacked = plot.grouping in ("stacked", "percentStacked")
    width = group if stacked else group / len(plot.series)
    base = [0.0] * length
    for slot, (series, values) in enumerate(zip(plot.series, rows, strict=True)):
        offset = 0.0 if stacked else -group / 2 + (slot + 0.5) * width
        positions = [index + offset for index in range(length)]
        # A spacer -- `noFill`, or no values at all -- keeps its slot, draws nothing.
        if series.color == "none" or all(math.isnan(v) for v in values):
            continue
        if plot.horizontal:
            bars = axes.barh(positions, values, width, left=base, color=series.color, zorder=2)
        else:
            bars = axes.bar(positions, values, width, bottom=base, color=series.color, zorder=2)
        if stacked:
            base = [b + (0.0 if math.isnan(v) else v) for b, v in zip(base, values, strict=True)]
        if series.name:
            # One bar stands for the series: a legend draws a patch the same way.
            handles.append((series.order, bars.patches[0], series.name))


def _draw_lines(axes: Axes, plot: Plot, handles: list[_Handle]) -> None:
    for series in plot.series:
        if series.color == "none":
            continue
        values = [math.nan if value is None else value for value in series.values]
        (line,) = axes.plot(range(len(values)), values, color=series.color, linewidth=2, zorder=3)
        if series.name:
            handles.append((series.order, line, series.name))


__all__ = [
    "CHART_HEIGHT_MM",
    "CHART_WIDTH_MM",
    "Axis",
    "Chart",
    "Plot",
    "Series",
    "draw",
    "load_diagram",
    "read_diagram",
]
