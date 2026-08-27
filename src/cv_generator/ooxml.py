"""The few OOXML constructs python-docx exposes no API for.

These reach into ``paragraph._p``, ``table._tbl`` and ``style.element`` on
purpose -- there is no public route to hyperlinks, borders, cell margins or run
language. Keeping them in one module means the private-API surface is a handful
of functions wide instead of scattered through the renderer.

Element *order* matters: WordprocessingML declares a fixed child sequence, and
Word silently "repairs" documents that violate it -- damage nobody notices until
a recruiter opens the file. python-docx orders the elements it knows about, so
these helpers only have to place their own.
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.shared import Length
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

# https://docs.microsoft.com/openspecs/office_standards/ms-oi29500 -- CT_PPr
# children that must precede w:pBdr.
_BEFORE_PBDR = frozenset(
    qn(tag)
    for tag in (
        "w:pStyle",
        "w:keepNext",
        "w:keepLines",
        "w:pageBreakBefore",
        "w:framePr",
        "w:widowControl",
        "w:numPr",
        "w:suppressLineNumbers",
    )
)

# CT_TblPr children that must precede w:tblBorders, and then the further ones
# that must also precede w:tblCellMar.
_BEFORE_TBL_BORDERS = frozenset(
    qn(tag)
    for tag in (
        "w:tblStyle",
        "w:tblpPr",
        "w:tblOverlap",
        "w:bidiVisual",
        "w:tblStyleRowBandSize",
        "w:tblStyleColBandSize",
        "w:tblW",
        "w:jc",
        "w:tblCellSpacing",
        "w:tblInd",
    )
)
_BEFORE_TBL_CELL_MAR = _BEFORE_TBL_BORDERS | {
    qn(tag) for tag in ("w:tblBorders", "w:shd", "w:tblLayout")
}

HYPERLINK_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)

TWIPS_PER_POINT = 20


def _insert_after(
    parent: BaseOxmlElement, element: BaseOxmlElement, precede: frozenset[str]
) -> None:
    """Insert ``element`` after the last child of ``parent`` that must precede it."""
    index = 0
    for position, child in enumerate(parent):
        if child.tag in precede:
            index = position + 1
    parent.insert(index, element)


def _single_bottom(*, color: str, size: int, space: int) -> BaseOxmlElement:
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    return bottom


def add_bottom_border(paragraph: Paragraph, *, color: str, size: int = 6, space: int = 2) -> None:
    """Draw a rule under ``paragraph``.

    Args:
        color: RGB hex without a leading ``#``.
        size: Line width in eighths of a point, so ``12`` is 1.5pt.
        space: Gap between text and rule, in points.
    """
    borders = OxmlElement("w:pBdr")
    borders.append(_single_bottom(color=color, size=size, space=space))
    _insert_after(paragraph._p.get_or_add_pPr(), borders, _BEFORE_PBDR)


def add_table_bottom_border(table: Table, *, color: str, size: int = 6) -> None:
    """Draw a rule under the whole of ``table``, spanning every column.

    The paragraph-level equivalent would only underline one cell, so a header
    laid out as columns needs the rule on the table instead.
    """
    borders = OxmlElement("w:tblBorders")
    borders.append(_single_bottom(color=color, size=size, space=0))
    _insert_after(table._tbl.tblPr, borders, _BEFORE_TBL_BORDERS)


def set_table_cell_margins(
    table: Table,
    *,
    top: float = 0.0,
    left: float = 0.0,
    bottom: float = 0.0,
    right: float = 0.0,
) -> None:
    """Set ``table``'s cell insets, in points.

    Word's default left inset would indent a layout table's text relative to the
    paragraphs around it; zeroing it keeps a two-column header aligned with the
    single-column body.

    The edges are keyword-only and written in the order ``CT_TblCellMar``
    declares -- top, left, bottom, right -- because that sequence is part of the
    schema too, not just the position of ``w:tblCellMar`` among its siblings.
    """
    element = OxmlElement("w:tblCellMar")
    for edge, points in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        child = OxmlElement(f"w:{edge}")
        child.set(qn("w:w"), str(round(points * TWIPS_PER_POINT)))
        child.set(qn("w:type"), "dxa")
        element.append(child)
    _insert_after(table._tbl.tblPr, element, _BEFORE_TBL_CELL_MAR)


def set_column_widths(table: Table, *widths: Length) -> None:
    """Fix ``table``'s column widths.

    Both the grid and the cells carry a width: Word prefers the grid, older
    readers the cells, and disagreement between them shows as a wrong layout.
    """
    table.autofit = False
    for index, width in enumerate(widths):
        table.columns[index].width = width
        for cell in table.columns[index].cells:
            cell.width = width


def remove_paragraph(paragraph: Paragraph) -> None:
    """Delete ``paragraph`` from its parent.

    A new table cell arrives with one empty paragraph. Filling the cell appends
    after it, so it has to go or the cell opens with a blank line.
    """
    element = paragraph._p
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def start_hyperlink(paragraph: Paragraph, url: str) -> BaseOxmlElement:
    """Open an external hyperlink at the end of ``paragraph``.

    Returns the ``w:hyperlink`` element; runs become part of the link only once
    they are moved into it with :func:`move_run_into`. Splitting it this way lets
    a link carry nested formatting (bold, code, ...) built with the normal
    python-docx run API.
    """
    relationship_id = paragraph.part.relate_to(url, HYPERLINK_RELATIONSHIP, is_external=True)
    element = OxmlElement("w:hyperlink")
    element.set(qn("r:id"), relationship_id)
    paragraph._p.append(element)
    return element


def move_run_into(run: Run, container: BaseOxmlElement) -> None:
    """Reparent ``run`` into ``container``, e.g. a ``w:hyperlink``.

    lxml moves rather than copies on append, so the run leaves its old position.
    """
    container.append(run._r)


def set_language(style: BaseStyle, lang: str) -> None:
    """Tag ``style`` with a language so Word spell-checks in the right one.

    ``w:lang`` sorts near the end of ``CT_RPr``, after everything python-docx
    writes, so appending is already in schema order.
    """
    properties = style.element.get_or_add_rPr()
    element = OxmlElement("w:lang")
    element.set(qn("w:val"), lang)
    properties.append(element)
