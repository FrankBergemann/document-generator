"""Render a :class:`~cv_generator.models.Document` to a self-contained HTML document.

This is also the input stage for PDF output: :mod:`cv_generator.pdf` prints the
HTML produced here in headless Chromium.

Two kinds of section content arrive here and leave as HTML: Markdown, converted
by :mod:`cv_generator.markdown`, and the block tree of a section imported from a
Word document, converted by :func:`blocks_to_html`. Both are exposed to the
template as filters, so a theme decides *where* the content goes and never how.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from markupsafe import Markup, escape

from cv_generator.errors import RenderError
from cv_generator.markdown import to_html
from cv_generator.models import Document, Photo, RichBlock, RichParagraph, RichRun, RichTable

BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"

# EMU (English Metric Units, what `wp:extent` is in) per CSS reference pixel:
# 914400 EMU/inch ÷ 96 px/inch.
_EMU_PER_PX = 9525

TEMPLATE_NAME = "document.html.j2"
STYLESHEET_NAME = "document.css"


class Renderer:
    """Turns a Document into HTML using a theme directory.

    A theme is a directory containing ``document.html.j2`` and ``document.css``. The
    stylesheet is inlined into the output so that a single HTML file is enough
    for any downstream PDF engine.

    Autoescape is on. Trusted markup -- the stylesheet and the HTML converted
    from the Document's Markdown -- is wrapped in :class:`Markup` here rather than
    marked ``| safe`` in the template, so a theme author cannot accidentally
    escape CSS (which would turn child selectors ``>`` into ``&gt;``) or
    double-escape rendered Markdown.
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir or BUILTIN_TEMPLATES_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(default_for_string=True, default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["markdown"] = _markdown_filter
        self._env.filters["blocks"] = _blocks_filter

    def available_themes(self) -> list[str]:
        """List theme directories that contain a template."""
        if not self.templates_dir.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.templates_dir.iterdir()
            if entry.is_dir() and (entry / TEMPLATE_NAME).is_file()
        )

    def render_html(self, doc: Document, theme: str | None = None) -> str:
        """Render ``doc`` to a complete HTML document."""
        name = theme or doc.theme
        try:
            template = self._env.get_template(f"{name}/{TEMPLATE_NAME}")
        except TemplateNotFound as exc:
            known = ", ".join(self.available_themes()) or "none"
            raise RenderError(
                f"theme {name!r} not found in {self.templates_dir} (available: {known})"
            ) from exc

        return template.render(document=doc, stylesheet=self._stylesheet(name))

    def _stylesheet(self, theme: str) -> Markup:
        path = self.templates_dir / theme / STYLESHEET_NAME
        if not path.is_file():
            return Markup()
        return Markup(path.read_text(encoding="utf-8"))


def _markdown_filter(text: str | None) -> Markup:
    """Jinja filter: Markdown fragment -> trusted HTML fragment."""
    return Markup(to_html(text)) if text else Markup()


def _blocks_filter(blocks: Sequence[RichBlock] | None) -> Markup:
    """Jinja filter: imported blocks -> trusted HTML fragment."""
    return Markup(blocks_to_html(blocks)) if blocks else Markup()


def blocks_to_html(blocks: Sequence[RichBlock]) -> str:
    """Convert imported ``.docx`` blocks to an HTML fragment.

    Text from the source document is escaped here; everything else is markup
    this function wrote, which is why the result may be trusted upstream.
    """
    return f'<div class="cv-blocks">{_blocks(blocks)}</div>'


def _blocks(blocks: Sequence[RichBlock]) -> str:
    """Emit blocks, gathering consecutive list items into one list."""
    parts: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if isinstance(block, RichTable):
            parts.append(_table(block))
            index += 1
        elif block.level is None:
            parts.append(f"<p{_paragraph_attr(block)}>{_runs(block.runs)}</p>")
            index += 1
        else:
            end = index
            while end < len(blocks) and _is_item(blocks[end]):
                end += 1
            # The slice is all list items, which `_list` relies on.
            parts.append(_list([b for b in blocks[index:end] if isinstance(b, RichParagraph)]))
            index = end
    return "".join(parts)


def _is_item(block: RichBlock) -> bool:
    return isinstance(block, RichParagraph) and block.level is not None


def _list(items: Sequence[RichParagraph], level: int = 0) -> str:
    """Emit one list, recursing into deeper levels as nested lists."""
    tag = "ol" if items[0].ordered else "ul"
    parts = [f"<{tag}>"]
    index = 0
    while index < len(items):
        item = items[index]
        index += 1
        # Anything deeper than this level belongs inside the item just emitted,
        # not after it -- a sibling <ul> would render at the wrong indent.
        start = index
        while index < len(items) and (items[index].level or 0) > level:
            index += 1
        nested = _list(items[start:index], level + 1) if index > start else ""
        parts.append(f"<li{_paragraph_attr(item)}>{_runs(item.runs)}{nested}</li>")
    parts.append(f"</{tag}>")
    return "".join(parts)


def _paragraph_attr(paragraph: RichParagraph) -> str:
    """A ``style`` attribute for what the paragraph itself carries, or nothing.

    The source's four alignment values (see :mod:`cv_generator.docx_import`)
    are valid CSS ``text-align`` values verbatim, so no translation table is
    needed here the way ``_run`` needs one for colour.

    A blank paragraph's own size goes into the same attribute as a
    ``font-size``: ``.cv-blocks p:empty`` is one line high, and that line is
    as tall as the source's paragraph mark made it.

    A page break becomes ``break-before``/``break-after``, which only paged
    media -- the PDF, a browser's print -- act on; on screen it is nothing.
    """
    declarations = []
    if paragraph.alignment:
        declarations.append(f"text-align:{paragraph.alignment}")
    if paragraph.blank_size_pt is not None:
        declarations.append(f"font-size:{paragraph.blank_size_pt:g}pt")
    if paragraph.page_break_before:
        declarations.append("break-before:page")
    if paragraph.page_break_after:
        declarations.append("break-after:page")
    return f' style="{";".join(declarations)}"' if declarations else ""


def _table(table: RichTable) -> str:
    classes = "cv-block-table"
    if table.bordered:
        classes += " cv-block-table--ruled"
    for edge in table.outer_rules:
        classes += f" cv-block-table--rule-{edge}"
    if table.centered:
        classes += " cv-block-table--centered"
    parts = [f'<table class="{classes}">']
    # A centered table is sized to its own content instead of the page, so the
    # source's column *proportions* would misdescribe it -- the browser's own
    # content-based sizing decides column widths instead.
    if not table.centered and len(table.column_widths) == max(
        (len(row) for row in table.rows), default=0
    ):
        columns = "".join(
            f'<col style="width:{width * 100:.4g}%">' for width in table.column_widths
        )
        parts.append(f"<colgroup>{columns}</colgroup>")
    parts.append("<tbody>")
    for row in table.rows:
        cells = "".join(
            f"<td{_rowspan_attr(cell.row_span)}>{_blocks(cell.paragraphs)}</td>"
            for cell in row
            if not cell.merged
        )
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _rowspan_attr(row_span: int) -> str:
    """A ``rowspan`` attribute for a vertically merged cell, or nothing."""
    return f' rowspan="{row_span}"' if row_span > 1 else ""


def _runs(runs: Sequence[RichRun]) -> str:
    return "".join(_run(run) for run in runs)


def _image_size_style(photo: Photo) -> str:
    """A ``width``/``aspect-ratio`` declaration from the source's own display size.

    Empty when the source had none (the Document's own identity photo, sized by
    the theme instead -- see :class:`~cv_generator.models.Photo`), which leaves
    ``.cv-inline-image``'s own rules -- natural size, capped by ``max-width`` --
    exactly as before this existed. ``aspect-ratio`` matters as much as
    ``width`` here: ``.cv-inline-image``'s ``max-width:100%`` still has to be
    able to shrink an image wider than its cell, and doing that through
    ``height:auto`` alone would derive the height from the embedded bitmap's
    own pixel dimensions -- usually a different, larger picture than the
    source actually showed -- instead of from the extent being set here.
    """
    if photo.width_emu is None or photo.height_emu is None:
        return ""
    width_px = photo.width_emu / _EMU_PER_PX
    return f' style="width:{width_px:.4g}px;aspect-ratio:{photo.width_emu}/{photo.height_emu}"'


def _is_cropped(photo: Photo) -> bool:
    return bool(photo.crop_left or photo.crop_top or photo.crop_right or photo.crop_bottom)


def _image_html(photo: Photo, float_side: Literal["left", "right"] | None) -> str:
    """An imported picture, at its source size and (if cropped) crop.

    An uncropped picture is a plain ``<img>``: ``.cv-inline-image`` already
    handles its size (see ``_image_size_style``). A cropped one needs a wrapper
    ``<span>`` sized to the *cropped* box, ``overflow: hidden``, holding an
    ``<img>`` sized and positioned (in percent, so it shrinks with the wrapper
    -- see ``.cv-inline-image--cropped`` in document.css) to show only the
    remainder Word's own crop tool kept -- CSS has no property for "show only
    this rectangle of an image", so this is the same trick as an
    object-position/object-fit crop, spelled out by hand for browsers this
    project's PDF engine is old enough to still need it spelled out for.
    """
    classes = "cv-inline-image"
    if float_side is not None:
        classes += f" cv-inline-image--float-{float_side}"
    style = _image_size_style(photo)
    src = escape(photo.data_uri())
    if not _is_cropped(photo):
        return f'<img class="{classes}"{style} src="{src}" alt="">'
    scale_w = max(1e-6, 1 - photo.crop_left - photo.crop_right)
    scale_h = max(1e-6, 1 - photo.crop_top - photo.crop_bottom)
    # `+ 0.0` folds a `-0.0` (an uncropped edge on an otherwise-cropped axis,
    # `-100 * 0.0`) back to plain `0`, which is what a reader expects to see
    # in the declaration -- `-0%` would be correct CSS but look like a typo.
    left = -100 * photo.crop_left / scale_w + 0.0
    top = -100 * photo.crop_top / scale_h + 0.0
    inner_style = (
        f"width:{100 / scale_w:.4g}%;height:{100 / scale_h:.4g}%;left:{left:.4g}%;top:{top:.4g}%"
    )
    inner = f'<img style="{inner_style}" src="{src}" alt="">'
    return f'<span class="{classes} cv-inline-image--cropped"{style}>{inner}</span>'


_FIELD_CLASSES = {"page": "pageNumber", "pages": "totalPages"}


def _run(run: RichRun) -> str:
    if run.image is not None:
        # Formatting flags (bold, colour, ...) do not apply to a picture; a
        # link around it does, the same as around text.
        html = _image_html(run.image, run.float_side)
        return f'<a href="{escape(run.link)}">{html}</a>' if run.link else html
    # A line break inside a paragraph (`w:br`, read as "\n") would collapse
    # into a space in HTML.
    html = str(escape(run.text)).replace("\n", "<br>")
    if run.field is not None:
        # The class names are Chromium's own: inside a page header/footer
        # template it fills them with the live page number/count (see
        # pdf/chrome.py). Anywhere else the cached value stays shown.
        html = f'<span class="{_FIELD_CLASSES[run.field]}">{html}</span>'
    if run.bold:
        html = f"<strong>{html}</strong>"
    if run.italic:
        html = f"<em>{html}</em>"
    if run.underline:
        html = f"<u>{html}</u>"
    if run.strike:
        html = f"<s>{html}</s>"
    if run.link:
        html = f'<a href="{escape(run.link)}">{html}</a>'
    declarations = []
    if run.size_pt is not None:
        declarations.append(f"font-size:{run.size_pt:.4g}pt")
    if run.color is not None:
        declarations.append(f"color:#{escape(run.color)}")
    if declarations:
        html = f'<span style="{";".join(declarations)}">{html}</span>'
    return html
