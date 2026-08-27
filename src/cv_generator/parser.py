"""Parse a CV Markdown file into a validated :class:`~cv_generator.models.CV`.

Source format::

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

``photo`` is the one key naming another file. Its path is resolved relative to
the CV file, and the image is read here rather than by the backends, so a model
is complete on its own and no output stage has to touch the filesystem.

One section is filled from elsewhere by convention rather than by a key:
``## Projekte`` takes its content from the Word project list that lives next to
the CV -- the single ``.docx`` whose name contains "Projektliste" -- and whatever
stands under the heading in the Markdown file is ignored. That list is maintained
in Word and sent to clients as it is, so Word is its source of truth; see
:mod:`cv_generator.docx_import`. As with the photo, the file is read here, so the
model still leaves the backends nothing to look up.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cv_generator.docx_import import find_docx, load_section
from cv_generator.errors import CVParseError
from cv_generator.models import CV, Photo, RichBlock, Section

FRONTMATTER_DELIM = "---"

PHOTO_KEY = "photo"

# The imported-projects convention, in one place: which section it replaces,
# which file it comes from, and which heading inside that file.
PROJECTS_SLUG = "projekte"
PROJECTS_DOCX_MARKER = "projektliste"
PROJECTS_DOCX_HEADING = "Projekthistorie"

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


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a document into its raw YAML frontmatter and its Markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        raise CVParseError(
            f"missing YAML frontmatter: the file must start with a {FRONTMATTER_DELIM!r} line"
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIM:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise CVParseError(
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
            of the CV file, so a CV and its photo travel together.

    Raises:
        CVParseError: if the value is not a path, the file cannot be read, or
            the image is not in a format both output backends support.
    """
    if not isinstance(reference, str) or not reference.strip():
        raise CVParseError(
            f"{source}: {PHOTO_KEY} must be a path to an image file, got {reference!r}"
        )

    path = Path(reference.strip())
    if not path.is_absolute():
        path = base_dir / path

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CVParseError(f"{source}: cannot read {PHOTO_KEY} {path}: {exc}") from exc

    media_type = next((mime for magic, mime in PHOTO_MAGIC if data.startswith(magic)), None)
    if media_type is None:
        supported = ", ".join(sorted({mime for _, mime in PHOTO_MAGIC}))
        raise CVParseError(f"{source}: {path} is not a supported image ({supported})")

    return Photo(data=data, media_type=media_type)


def load_projects(base_dir: Path, *, source: str = "<string>") -> tuple[list[RichBlock], Path]:
    """Load the project blocks that replace the ``## Projekte`` section's body.

    Args:
        base_dir: Directory to look in -- the CV file's own, so a CV and its
            project list travel together the way a CV and its photo do.

    Returns:
        The imported blocks and the file they came from.

    Raises:
        CVParseError: if the directory holds no matching ``.docx`` or more than
            one, or if the file has no ``Projekthistorie`` heading. The section
            exists, so an empty one is a mistake, not a valid outcome.
    """
    try:
        path = find_docx(base_dir, PROJECTS_DOCX_MARKER)
        return load_section(path, PROJECTS_DOCX_HEADING), path
    except CVParseError as exc:
        raise CVParseError(
            f"{source}: the '{PROJECTS_SLUG}' section is imported from the "
            f"{PROJECTS_DOCX_MARKER!r} document: {exc}"
        ) from exc


def parse_cv(text: str, *, source: str = "<string>", base_dir: Path | None = None) -> CV:
    """Parse CV Markdown into a validated :class:`CV`.

    Args:
        base_dir: Directory the ``photo:`` path is resolved against; defaults to
            the working directory, which is what a string with no file behind it
            can offer.

    Raises:
        CVParseError: if the frontmatter is missing, is not a YAML mapping, names
            a photo that cannot be read, or does not satisfy the :class:`CV`
            schema.
    """
    raw_meta, body = split_frontmatter(text)

    try:
        meta: Any = yaml.safe_load(raw_meta)
    except yaml.YAMLError as exc:
        raise CVParseError(f"{source}: invalid YAML frontmatter: {exc}") from exc

    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise CVParseError(
            f"{source}: frontmatter must be a YAML mapping, got {type(meta).__name__}"
        )

    photo = None
    if meta.get(PHOTO_KEY) is not None:
        photo = load_photo(meta[PHOTO_KEY], base_dir or Path(), source=source)

    summary, raw_sections = split_sections(body)

    seen: dict[str, int] = {}
    sections: list[Section] = []
    for title, section_body in raw_sections:
        slug = slugify(title) or "section"
        count = seen.get(slug, 0) + 1
        seen[slug] = count
        slug = slug if count == 1 else f"{slug}-{count}"

        if slug == PROJECTS_SLUG:
            blocks, docx_path = load_projects(base_dir or Path(), source=source)
            sections.append(
                Section(
                    title=title,
                    slug=slug,
                    # Emptied on purpose: the Markdown body of this section is
                    # not the content, and no backend should render both.
                    markdown="",
                    blocks=blocks,
                    imported_from=str(docx_path),
                )
            )
            continue

        sections.append(Section(title=title, slug=slug, markdown=section_body))

    try:
        return CV.model_validate(
            {
                **meta,
                PHOTO_KEY: photo,
                "summary": summary or None,
                "sections": sections,
            }
        )
    except ValidationError as exc:
        raise CVParseError(f"{source}: {exc}") from exc


def parse_cv_file(path: Path) -> CV:
    """Read and parse a CV Markdown file from disk."""
    try:
        # utf-8-sig transparently strips a byte-order mark if one is present.
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CVParseError(f"cannot read {path}: {exc}") from exc
    return parse_cv(text, source=str(path), base_dir=path.parent)
