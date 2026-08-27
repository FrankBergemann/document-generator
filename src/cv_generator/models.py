"""Validated data model for a CV.

The model deliberately keeps section *content* as raw Markdown rather than
modelling every possible CV structure (jobs, dates, bullet lists, ...) and
rather than pre-rendering it to HTML. Markdown is the one representation every
output backend can consume: the HTML renderer converts it to HTML, the Word
renderer walks its syntax tree. Pre-rendering to HTML would force ``.docx``
output to parse HTML back into structure.

So the model only gives structure to the things a backend must *position*:
identity, contact details, an optional photo and the ordered list of sections.

The one exception is a section whose content is *imported* from an existing
``.docx`` (see :mod:`cv_generator.docx_import`). Markdown cannot express what
such a section looks like -- a two-column table with a bullet list in one cell
-- and a Word document is not Markdown, so those sections carry ``blocks``: a
small format-neutral tree of paragraphs, runs and tables that both backends can
render. It is deliberately the poorest description that still keeps the source
document's formatting: weight, size, colour, links, bullets, table geometry.
"""

from __future__ import annotations

import base64
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Link(BaseModel):
    """A labelled external URL, e.g. GitHub or LinkedIn."""

    model_config = ConfigDict(extra="forbid")

    label: str
    url: str


class Contact(BaseModel):
    """Contact block rendered in the CV header."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[Link] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.email or self.phone or self.location or self.links)


class Photo(BaseModel):
    """A portrait photo, carried as bytes rather than as a path.

    The frontmatter names a file, but the model holds its content: the HTML
    output has to stay self-contained (the PDF browser may live in another
    container and never sees this filesystem), and ``.docx`` embeds the bytes
    too. Reading the file once, in the parser, keeps both backends off the disk.
    """

    model_config = ConfigDict(extra="forbid")

    data: bytes
    media_type: str

    def data_uri(self) -> str:
        """The photo as a ``data:`` URL, for embedding in HTML."""
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


class RichRun(BaseModel):
    """A stretch of text with the formatting it carried in the source document.

    Font *family* is deliberately absent: it is the one attribute the CV's own
    theme should keep deciding, and a Word document usually names it indirectly
    (a theme font) anyway.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    size_pt: float | None = None
    color: str | None = None
    link: str | None = None


class RichParagraph(BaseModel):
    """One imported paragraph, or one list item when ``level`` is set."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["paragraph"] = "paragraph"
    runs: list[RichRun] = Field(default_factory=list)
    # 0-based nesting depth of a bullet/number, or None for a plain paragraph.
    level: int | None = None
    ordered: bool = False

    def text(self) -> str:
        return "".join(run.text for run in self.runs)


class RichCell(BaseModel):
    """One table cell. Cells hold paragraphs only; a nested table is dropped."""

    model_config = ConfigDict(extra="forbid")

    paragraphs: list[RichParagraph] = Field(default_factory=list)


class RichTable(BaseModel):
    """An imported table, with just enough geometry to lay it out again."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["table"] = "table"
    rows: list[list[RichCell]] = Field(default_factory=list)
    bordered: bool = False
    # Column widths as fractions of the table width, or empty if the source did
    # not fix them. Fractions rather than absolute widths: the CV's page may be
    # narrower than the document the table came from.
    column_widths: list[float] = Field(default_factory=list)


# Discriminated on `kind`, so a round-trip through JSON cannot confuse the two.
RichBlock = Annotated[RichParagraph | RichTable, Field(discriminator="kind")]


class Section(BaseModel):
    """One ``##`` section of the Markdown body, with its body as Markdown.

    A section whose content came from an existing ``.docx`` carries ``blocks``
    instead, with ``markdown`` empty and ``imported_from`` naming the file.
    Exactly one of the two is ever populated, so a backend cannot render both.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    slug: str
    markdown: str
    blocks: list[RichBlock] = Field(default_factory=list)
    imported_from: str | None = None


class CV(BaseModel):
    """A complete CV, ready to hand to any output backend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    headline: str | None = None
    lang: str = "de"
    theme: str = "classic"
    contact: Contact = Field(default_factory=Contact)
    photo: Photo | None = None
    summary: str | None = None
    sections: list[Section] = Field(default_factory=list)

    def section(self, slug: str) -> Section | None:
        """Look up a section by slug, or ``None`` if the CV has no such section."""
        return next((s for s in self.sections if s.slug == slug), None)
