"""Turn the source files into a validated :class:`~cv_generator.models.Document`.

There are two ways in, and they produce the same model.

**A single Markdown file** -- YAML frontmatter, then Markdown::

    ---
    name: Frank Bergemann
    headline: Senior Software Engineer
    photo: photo.jpg
    contact:
      email: frank@example.com
    ---

    Optional summary paragraph, before the first section.

    ## Experience

    ### Senior Engineer - ACME GmbH
    ...

Everything above the closing ``---`` is YAML metadata. Everything below is
Markdown: text before the first ``##`` becomes the summary, and each ``##``
heading starts a section. Section bodies are kept as Markdown -- converting them
is the job of an output backend, not of the parser.

**A ``config.json``**, when the document is assembled from several files: any
number of spans copied out of ``.md``, ``.docx`` and ``.xlsx`` sources -- a
Markdown or Word span bounded by the headlines it begins and ends at, an Excel
one by the cell rectangle it names. The header rides along with the first span
that starts at the top of a Markdown file, since frontmatter is part of that
beginning. See :mod:`cv_generator.config` for the recipe's shape,
:mod:`cv_generator.docx_import` for how a Word section is read and
:mod:`cv_generator.xlsx_import` for how a cell rectangle is. Either way the
backends see one finished model and never learn how many files went into it.

Referenced files are read *here* rather than by the backends, so a model is
complete on its own: ``photo`` is resolved relative to the Markdown file that
names it and carried as bytes, and an imported Word or Excel section arrives as
blocks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from pydantic import ValidationError

from cv_generator.config import (
    CONFIG_SUFFIX,
    BuildConfig,
    SectionSpec,
    load_config,
    resolve_source,
)
from cv_generator.docx_import import load_footer as load_docx_footer
from cv_generator.docx_import import load_header as load_docx_header
from cv_generator.docx_import import load_section as load_docx_section
from cv_generator.errors import DocParseError
from cv_generator.models import Document, Photo, RichBlock, Section
from cv_generator.xlsx_import import load_section as load_xlsx_section

FRONTMATTER_DELIM = "---"

PHOTO_KEY = "photo"

# The output stem a recipe with no Markdown entry falls back to, since there is
# then no header file to take a stem from. `output`/`target` still override it,
# same as they override a Markdown-derived stem.
DEFAULT_NAME = "document"

# Sniffed from the content rather than trusted from the file extension. Only the
# formats *both* backends handle are accepted -- browsers also read WebP and
# python-docx also reads BMP and TIFF, but a photo that renders in one output
# format and not the other is worse than a parse error naming the reason.
PHOTO_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_H2 = re.compile(r"^##[ \t]+(?P<title>.+?)[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Turn a section title into a URL/CSS-safe slug.

    Umlauts and other accents are folded to ASCII so that "Berufserfahrung" and
    "Persönliches" both produce usable slugs.
    """
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    return _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")


class _Slugger:
    """Slugs for one document's sections, kept distinct from each other.

    A counter rather than a plain :func:`slugify`, because slugs are the HTML
    anchors: two sections called "Kenntnisse" -- easily done once they come from
    two different files -- would otherwise share an ``id``.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def __call__(self, title: str) -> str:
        slug = slugify(title) or "section"
        count = self._seen.get(slug, 0) + 1
        self._seen[slug] = count
        return slug if count == 1 else f"{slug}-{count}"


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a document into its raw YAML frontmatter and its Markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        raise DocParseError(
            f"missing YAML frontmatter: the file must start with a {FRONTMATTER_DELIM!r} line"
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIM:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise DocParseError(
        f"unterminated YAML frontmatter: no closing {FRONTMATTER_DELIM!r} line was found"
    )


def split_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a Markdown body into its summary and its ``##`` sections.

    ``##`` lines inside fenced code blocks are treated as content, not headings.
    """
    summary: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    in_fence = False

    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _H2.match(line)
        if heading is not None:
            sections.append((heading.group("title"), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            summary.append(line)

    return (
        "\n".join(summary).strip(),
        [(title, "\n".join(lines).strip()) for title, lines in sections],
    )


def load_photo(reference: Any, base_dir: Path, *, source: str = "<string>") -> Photo:
    """Read the image named by a ``photo:`` frontmatter value.

    Args:
        reference: The raw frontmatter value; must be a path-like string.
        base_dir: Directory relative paths are resolved against -- the directory
            of the Document file, so a Document and its photo travel together.

    Raises:
        DocParseError: if the value is not a path, the file cannot be read, or
            the image is not in a format both output backends support.
    """
    if not isinstance(reference, str) or not reference.strip():
        raise DocParseError(
            f"{source}: {PHOTO_KEY} must be a path to an image file, got {reference!r}"
        )

    path = Path(reference.strip())
    if not path.is_absolute():
        path = base_dir / path

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DocParseError(f"{source}: cannot read {PHOTO_KEY} {path}: {exc}") from exc

    media_type = next((mime for magic, mime in PHOTO_MAGIC if data.startswith(magic)), None)
    if media_type is None:
        supported = ", ".join(sorted({mime for _, mime in PHOTO_MAGIC}))
        raise DocParseError(f"{source}: {path} is not a supported image ({supported})")

    return Photo(data=data, media_type=media_type)


# -- the single Markdown file --------------------------------------------


def parse_doc(text: str, *, source: str = "<string>", base_dir: Path | None = None) -> Document:
    """Parse Document Markdown into a validated :class:`Document`.

    Args:
        base_dir: Directory the ``photo:`` path is resolved against; defaults to
            the working directory, which is what a string with no file behind it
            can offer.

    Raises:
        DocParseError: if the frontmatter is missing, is not a YAML mapping, names
            a photo that cannot be read, or does not satisfy the :class:`Document`
            schema.
    """
    raw_meta, body = split_frontmatter(text)
    meta = _meta_of(raw_meta, source=source)
    photo = _photo_of(meta, base_dir or Path(), source=source)
    summary, raw_sections = split_sections(body)

    slug_for = _Slugger()
    sections = [
        Section(title=title, slug=slug_for(title), markdown=markdown)
        for title, markdown in raw_sections
    ]
    return _validated(meta, photo, summary, sections, [], [], source=source)


def parse_doc_file(path: Path) -> Document:
    """Read and parse a Document Markdown file from disk."""
    return parse_doc(_read(path), source=str(path), base_dir=path.parent)


# -- the assembled document ----------------------------------------------


class LoadedDocument(NamedTuple):
    """A Document, the stem its output files take, and where to write them.

    ``target``, when set, is the whole output path relative to the project
    root and without an extension -- a format's own suffix is appended by the
    caller. ``None`` means the recipe named no ``target``, so the caller falls
    back to its own default location, built from ``name``.
    """

    doc: Document
    name: str
    target: Path | None = None


@dataclass(frozen=True)
class _Header:
    """What the top of a Markdown file contributes besides sections."""

    meta: dict[str, Any]
    photo: Photo | None
    summary: str
    # The file's stem, which is what the outputs are called unless `output` says.
    name: str


def build_doc(
    config: BuildConfig,
    base_dir: Path,
    *,
    source: str = "<config>",
    project_root: Path | None = None,
) -> LoadedDocument:
    """Assemble a :class:`Document` from the files a :class:`BuildConfig` names.

    The header is not named by a key of its own: it comes from the first entry
    whose span starts at the top of a Markdown file, because frontmatter is part
    of that beginning. A later entry starting at the top of another file
    contributes only its sections -- the Document has one name and one summary, and the
    first entry to supply them is the one that does. A recipe with no Markdown
    entry at all -- an invoice assembled purely from ``.docx``/``.xlsx``, say --
    gets a bare header instead: no name, headline, contact or summary, and the
    default output stem (see :data:`DEFAULT_NAME`). ``config.photo``, resolved
    the same way a section's ``source`` is, then still supplies a photo either
    way -- see :func:`cv_generator.config.resolve_source`.

    ``page_header``/``page_footer`` both come from the recipe's *first* entry,
    exclusively, when it is a ``.docx`` -- not the first entry's identity
    header above (name/headline/contact/photo, which may come from a later,
    Markdown entry instead), and not whichever entry happens to carry a page
    header or footer. One source of truth for both avoids a document whose
    page furniture is stitched together from two different letterheads.

    Args:
        base_dir: Directory every ``source`` is resolved against -- the config
            file's own, so a recipe and its ingredients travel together.
        project_root: Fallback directory for a ``source`` not found beside the
            config -- see :func:`cv_generator.config.resolve_source`.

    Returns:
        The finished Document, the stem its outputs default to, and the recipe's
        ``target`` resolved against ``project_root`` (``Path.cwd()`` if none
        was given), or ``None`` if the recipe named no ``target``.

    Raises:
        DocParseError: if a named file is missing, ambiguous, of a format its
            declared rectangle or headlines do not match, or does not contain
            what an entry asks for. Every message names the entry it came from,
            since a recipe has many.
    """
    slug_for = _Slugger()
    sections: list[Section] = []
    header: _Header | None = None
    first_docx_path: Path | None = None

    for index, spec in enumerate(config.sections):
        where = f"{source}: sections[{index}]"
        path = resolve_source(base_dir, spec.source, source=where, project_root=project_root)
        if index == 0 and spec.format == "docx":
            first_docx_path = path

        if spec.format == "docx":
            sections.append(_copy_docx(spec, path, slug_for, source=where))
            continue
        if spec.format == "xlsx":
            sections.append(_copy_xlsx(spec, path, slug_for, source=where))
            continue

        text = _read(path)
        if header is None and spec.begin is None:
            header = _header_of(text, path, source=where)
        sections.extend(_copy_markdown(spec, path, text, slug_for, source=where))

    if header is None:
        header = _Header(meta={}, photo=None, summary="", name=DEFAULT_NAME)

    photo = header.photo
    if config.photo is not None:
        photo_path = resolve_source(
            base_dir, config.photo, source=source, project_root=project_root
        )
        # `photo_path` is already fully resolved; splitting and rejoining it is
        # what lets `load_photo` (which resolves a *reference* against a
        # `base_dir`) take an already-resolved path without re-interpreting it.
        photo = load_photo(photo_path.name, photo_path.parent, source=source)

    # The first entry's own page header and footer, when it is a `.docx` --
    # not just the first `.docx` entry anywhere in the recipe, which could be
    # preceded by a Markdown or `.xlsx` entry that is what actually begins the
    # document.
    page_header: list[RichBlock] = []
    page_footer: list[RichBlock] = []
    if first_docx_path is not None:
        page_header = load_docx_header(first_docx_path)
        page_footer = load_docx_footer(first_docx_path)

    target = None
    if config.target is not None:
        target_path = Path(config.target)
        root = project_root if project_root is not None else Path.cwd()
        target = target_path if target_path.is_absolute() else root / target_path

    return LoadedDocument(
        _validated(
            header.meta, photo, header.summary, sections, page_header, page_footer, source=source
        ),
        config.output or header.name,
        target,
    )


def parse_config_file(path: Path) -> Document:
    """Read a ``config.json`` and assemble the document it describes."""
    return build_doc(load_config(path), path.parent, source=str(path), project_root=Path.cwd()).doc


def load_doc(path: Path) -> LoadedDocument:
    """Load whatever a build was pointed at: a ``config.json`` or a single ``.md``.

    The suffix decides, so one argument covers both and neither needs a flag.
    """
    if path.suffix.lower() == CONFIG_SUFFIX:
        return build_doc(load_config(path), path.parent, source=str(path), project_root=Path.cwd())
    return LoadedDocument(parse_doc_file(path), path.stem)


def _header_of(text: str, path: Path, *, source: str) -> _Header:
    """The frontmatter and summary of a file a span starts at the top of."""
    try:
        raw_meta, body = split_frontmatter(text)
    except DocParseError as exc:
        raise DocParseError(
            f"{source}: this is the first section to start at the beginning of a Markdown "
            f"file, so {path.name} supplies the Document's header -- {exc}"
        ) from exc

    meta = _meta_of(raw_meta, source=str(path))
    return _Header(
        meta=meta,
        # Relative to the Markdown file that names the photo, not to the config:
        # the `photo:` key is that file's, and it travels with it.
        photo=_photo_of(meta, path.parent, source=str(path)),
        summary=split_sections(body)[0],
        name=path.stem,
    )


def _copy_docx(spec: SectionSpec, path: Path, slug_for: _Slugger, *, source: str) -> Section:
    """One section, from the Word document's blocks under ``begin``.

    Always one and never several: the imported blocks are paragraphs and tables
    with no headings of their own, so there is nothing to split them at. The
    title comes from ``title`` if given, else the heading it starts at
    (``begin``); with no heading to be named after either, the section renders
    with no heading at all rather than one made of the source file's own
    filename, which is not a title -- it names the file, not what is in it.
    The slug still falls back to the file's stem, since an anchor has to point
    *somewhere* even when nothing is shown for it.
    """
    title = spec.title or spec.begin

    try:
        blocks = load_docx_section(path, spec.begin, spec.end)
    except DocParseError as exc:
        raise DocParseError(f"{source}: {exc}") from exc

    return Section(
        title=title,
        slug=slug_for(title or path.stem),
        # Empty on purpose: the content is `blocks`, and no backend may be given
        # the chance to render two sources for one section.
        markdown="",
        blocks=blocks,
        source=str(path),
    )


def _copy_xlsx(spec: SectionSpec, path: Path, slug_for: _Slugger, *, source: str) -> Section:
    """One section, from the rectangle of cells ``spec`` names.

    Always one and never several, for the same reason as a ``.docx`` import: a
    cell rectangle has no headings to split it at. Unlike a ``.docx`` entry
    there is no ``begin`` heading to fall back on either, so with no ``title``
    the section renders with no heading at all -- see :func:`_copy_docx` for
    why a filename does not stand in for one.
    """
    title = spec.title

    # `SectionSpec._rectangle_matches_format` guarantees all four are set
    # together with format "xlsx".
    assert spec.col_start is not None
    assert spec.col_end is not None
    assert spec.row_start is not None
    assert spec.row_end is not None

    try:
        blocks = load_xlsx_section(
            path,
            col_start=spec.col_start,
            col_end=spec.col_end,
            row_start=spec.row_start,
            row_end=spec.row_end,
            noframes=bool(spec.noframes),
        )
    except DocParseError as exc:
        raise DocParseError(f"{source}: {exc}") from exc

    return Section(
        title=title,
        slug=slug_for(title or path.stem),
        markdown="",
        blocks=blocks,
        source=str(path),
    )


def _copy_markdown(
    spec: SectionSpec, path: Path, text: str, slug_for: _Slugger, *, source: str
) -> list[Section]:
    """The span between two headlines, split at its ``##`` headings as usual.

    Splitting rather than keeping the span whole is what lets one entry stand for
    several sections -- "everything from Kenntnisse on" is one line in the recipe
    and three sections in the document, each with its own heading and anchor.

    A span with no ``begin`` starts at the file's first heading. Text above it is
    the summary, which :func:`_header_of` has already taken if this is the entry
    that supplies the header, and is not section content either way.
    """
    body = _markdown_body(text, source=str(path))
    found = split_sections(body)[1]
    titles = [title for title, _ in found]

    start = 0
    if spec.begin is not None:
        located = _index_of(titles, spec.begin, source=source)
        if located is None:
            raise DocParseError(
                f"{source}: {path.name} has no heading matching {spec.begin!r}; "
                f"it has {_listed(titles)}"
            )
        start = located

    stop = len(found)
    if spec.end is not None:
        # The end has to come after the beginning. With no `begin` the span starts
        # above the first heading, so that heading may itself be the end -- which
        # is how an entry takes a file's header and none of its sections.
        searched_from = start if spec.begin is not None else -1
        after = _index_of(titles, spec.end, after=searched_from, source=source)
        if after is None:
            raise DocParseError(
                f"{source}: {path.name} has no heading matching {spec.end!r} after "
                f"{_since(spec.begin)}; what follows is {_listed(titles[searched_from + 1 :])}"
            )
        stop = after

    copied: list[Section] = []
    for offset, (title, markdown) in enumerate(found[start:stop]):
        # `title` renames the span's first section, which is the one the entry
        # was addressed by; the rest keep the headings they carry.
        heading = spec.title if offset == 0 and spec.title else title
        copied.append(
            Section(title=heading, slug=slug_for(heading), markdown=markdown, source=str(path))
        )
    return copied


def _markdown_body(text: str, *, source: str) -> str:
    """The Markdown below a file's frontmatter, or all of it if it has none.

    Lenient where :func:`parse_doc` is strict: a file used only as a *section
    source* is not required to be a Document, so it need not carry frontmatter at all.
    An opened-but-unclosed ``---`` still fails, because that is a broken header
    rather than an absent one.
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == FRONTMATTER_DELIM:
        try:
            return split_frontmatter(text)[1]
        except DocParseError as exc:
            raise DocParseError(f"{source}: {exc}") from exc
    return text


def _index_of(titles: list[str], wanted: str, *, after: int = -1, source: str) -> int | None:
    """Where ``wanted`` first matches a headline, searched from ``after`` on.

    ``wanted`` is a regular expression, matched case-insensitively and in full
    against the headline (``re.fullmatch``) -- the same span an exact comparison
    covered before regular expressions were allowed, so plain heading text, which
    has no regex syntax in it, keeps matching itself exactly. A *partial* match
    would be too loose to use for finding a heading: a title such as "Projekte"
    would then also match "Weitere Projekte", or a mention of the word in a
    paragraph above the real heading. Surrounding whitespace is ignored, and a
    leading ``##`` is allowed: a recipe may quote the heading line or just its
    text, and the two must not mean different things.
    """
    pattern = _compile_headline(wanted, source=source)
    return next(
        (
            index
            for index in range(after + 1, len(titles))
            if pattern.fullmatch(_headline(titles[index]))
        ),
        None,
    )


def _compile_headline(text: str, *, source: str) -> re.Pattern[str]:
    """Compile a ``begin``/``end`` value into the pattern it is matched as.

    Raises:
        DocParseError: if ``text`` is not a valid regular expression -- a recipe
            mistake, worth failing on before any file is even opened for it.
    """
    try:
        return re.compile(_headline(text), re.IGNORECASE)
    except re.error as exc:
        raise DocParseError(f"{source}: {text!r} is not a valid regular expression: {exc}") from exc


def _headline(text: str) -> str:
    return text.lstrip("#").strip()


def _since(begin: str | None) -> str:
    return "the top of the file" if begin is None else f"heading matching {begin!r}"


def _listed(titles: list[str]) -> str:
    return ", ".join(f"'{title}'" for title in titles) or "nothing"


# -- shared by both ways in ----------------------------------------------


def _read(path: Path) -> str:
    try:
        # utf-8-sig transparently strips a byte-order mark if one is present.
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DocParseError(f"cannot read {path}: {exc}") from exc


def _meta_of(raw_meta: str, *, source: str) -> dict[str, Any]:
    try:
        meta: Any = yaml.safe_load(raw_meta)
    except yaml.YAMLError as exc:
        raise DocParseError(f"{source}: invalid YAML frontmatter: {exc}") from exc

    if meta is None:
        return {}
    if not isinstance(meta, dict):
        raise DocParseError(
            f"{source}: frontmatter must be a YAML mapping, got {type(meta).__name__}"
        )
    return meta


def _photo_of(meta: dict[str, Any], base_dir: Path, *, source: str) -> Photo | None:
    if meta.get(PHOTO_KEY) is None:
        return None
    return load_photo(meta[PHOTO_KEY], base_dir, source=source)


def _validated(
    meta: dict[str, Any],
    photo: Photo | None,
    summary: str,
    sections: list[Section],
    page_header: list[RichBlock],
    page_footer: list[RichBlock],
    *,
    source: str,
) -> Document:
    try:
        return Document.model_validate(
            {
                **meta,
                PHOTO_KEY: photo,
                "summary": summary or None,
                "sections": sections,
                "page_header": page_header,
                "page_footer": page_footer,
            }
        )
    except ValidationError as exc:
        raise DocParseError(f"{source}: {exc}") from exc
