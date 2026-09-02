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

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from markupsafe import Markup, escape

from cv_generator.errors import RenderError
from cv_generator.markdown import to_html
from cv_generator.models import Document, RichBlock, RichParagraph, RichRun, RichTable

BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"

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
            parts.append(f"<p{_align_attr(block.alignment)}>{_runs(block.runs)}</p>")
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
        parts.append(f"<li{_align_attr(item.alignment)}>{_runs(item.runs)}{nested}</li>")
    parts.append(f"</{tag}>")
    return "".join(parts)


def _align_attr(alignment: str | None) -> str:
    """A ``style="text-align:…"`` attribute, or nothing when unset.

    The source's four alignment values (see :mod:`cv_generator.docx_import`)
    are valid CSS ``text-align`` values verbatim, so no translation table is
    needed here the way ``_run`` needs one for colour.
    """
    return f' style="text-align:{alignment}"' if alignment else ""


def _table(table: RichTable) -> str:
    classes = "cv-block-table"
    if table.bordered:
        classes += " cv-block-table--ruled"
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
        cells = "".join(f"<td>{_blocks(cell.paragraphs)}</td>" for cell in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _runs(runs: Sequence[RichRun]) -> str:
    return "".join(_run(run) for run in runs)


def _run(run: RichRun) -> str:
    if run.image is not None:
        # Formatting flags (bold, colour, ...) do not apply to a picture; a
        # link around it does, the same as around text.
        html = f'<img class="cv-inline-image" src="{escape(run.image.data_uri())}" alt="">'
        return f'<a href="{escape(run.link)}">{html}</a>' if run.link else html
    html = str(escape(run.text))
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
