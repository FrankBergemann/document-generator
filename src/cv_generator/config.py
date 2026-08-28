"""The build recipe: which sections the target document has, and where each comes from.

A CV is normally assembled from more than one file. The prose is written in
Markdown, but a project list is maintained in Word and sent to clients from
there, so Word stays its source of truth; a second CV may reuse the same project
list with a different summary. ``config.json`` is where that composition is
written down::

    {
      "sections": [
        {"source": "document.md",                                        "end": "Kenntnisse"},
        {"source": "*Projektliste*.docx", "begin": "Projekthistorie", "end": "Ausbildung",
         "title": "Projekte"},
        {"source": "document.md",              "begin": "Kenntnisse"}
      ]
    }

Every entry copies one span out of one source file, and the spans are
concatenated in the order they are listed. A file may be used any number of
times, and the spans need not be in the source's own order.

Three rules decide what a span *is*:

* **``begin`` and ``end`` are headlines, and neither is required.** The span runs
  from ``begin`` up to but not including ``end``: ``end`` is the headline that
  starts the *next* thing, so it is not copied. Leave ``begin`` out and the span
  starts at the top of the file; leave ``end`` out and it runs to the bottom.
  Both rules hold for both source types, so moving content between a ``.md`` and
  a ``.docx`` does not change what an entry means.
* **A span that starts at the top of a Markdown file brings the header with it.**
  Frontmatter is part of the beginning of the document, so the first such entry
  is where the CV's name, headline, contact, photo and summary come from -- there
  is no separate key naming a metadata file, because that would be a second way
  to say the same thing. An entry that wants the header and none of the file's
  sections ends at its first heading.
* **A span may cover several headlines.** A Markdown span is split at its ``##``
  headings the way a single-file CV is, so one entry can contribute several
  sections; a ``.docx`` span is one section, since imported blocks carry no
  headings of their own. That is what lets three entries describe a five-section
  document.

``source`` is resolved relative to this file's own directory, so a config and the
files it names travel together. It may be a glob -- ``*Projektliste*.docx``
matches a list whose name carries a date, which a literal name would not survive
-- and then has to match exactly one file: picking one of several would quietly
publish a CV built from last year's list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cv_generator.docx_import import DOCX_SUFFIX, LOCK_PREFIX
from cv_generator.errors import CVParseError

MARKDOWN_SUFFIX = ".md"
SOURCE_SUFFIXES = (MARKDOWN_SUFFIX, DOCX_SUFFIX)

CONFIG_SUFFIX = ".json"

# Only these make a value a pattern. Everything else is a plain relative path, so
# a file really named "cv (2).md" is not accidentally read as a glob.
_GLOB_CHARS = "*?["


class SectionSpec(BaseModel):
    """One span of one source file, copied into the target document."""

    model_config = ConfigDict(extra="forbid")

    source: str
    # None means "from the top of the document" -- which, for Markdown, is where
    # the frontmatter is, so such a span can also supply the CV's header.
    begin: str | None = None
    # None means "to the end of the document". Otherwise the headline where
    # copying stops -- it belongs to what comes next and is not copied.
    end: str | None = None
    # Renames the first section the span produces. The imported project list is
    # headed "Projekthistorie" in Word and "Projekte" in the CV; without this the
    # target would have to adopt the source document's wording.
    title: str | None = None


class BuildConfig(BaseModel):
    """A whole ``config.json``."""

    model_config = ConfigDict(extra="forbid")

    sections: list[SectionSpec] = Field(min_length=1)
    # The stem of the files a build writes (dist/<output>.html, ...). Defaults to
    # that of the file the header came from, which is what keeps a recipe built
    # around `document.md` producing `dist/document.*` with nothing said about it.
    output: str | None = None


def load_config(path: Path) -> BuildConfig:
    """Read and validate a ``config.json``.

    Raises:
        CVParseError: if the file cannot be read, is not valid JSON, is not a
            JSON object, or does not satisfy :class:`BuildConfig` -- including an
            unknown key, which is a typo rather than an extension.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CVParseError(f"cannot read {path}: {exc}") from exc

    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CVParseError(f"{path}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise CVParseError(f"{path}: the config must be a JSON object, got {type(raw).__name__}")

    try:
        return BuildConfig.model_validate(raw)
    except ValidationError as exc:
        raise CVParseError(f"{path}: {exc}") from exc


def resolve_source(base_dir: Path, reference: str, *, source: str = "<config>") -> Path:
    """Turn a ``source`` value into the one file it names.

    A value with no glob character in it is a plain path, relative to
    ``base_dir`` unless it is absolute. A value with one is matched against
    ``base_dir`` and has to hit exactly one file; Word's ``~$…`` lock file never
    counts, or having the document open would break every build -- exactly when
    someone is most likely to rebuild.

    Raises:
        CVParseError: if the value is empty, names a file that is not there, or
            is a pattern matching no file or several.
    """
    reference = reference.strip()
    if not reference:
        raise CVParseError(f"{source}: a source must name a file, got an empty string")

    if not any(char in reference for char in _GLOB_CHARS):
        path = Path(reference)
        path = path if path.is_absolute() else base_dir / path
        if not path.is_file():
            raise CVParseError(f"{source}: no such file: {path}")
        return path

    matches = sorted(
        match
        for match in base_dir.glob(reference)
        if match.is_file() and not match.name.startswith(LOCK_PREFIX)
    )
    if not matches:
        raise CVParseError(f"{source}: no file in {base_dir} matches {reference!r}")
    if len(matches) > 1:
        names = ", ".join(match.name for match in matches)
        raise CVParseError(
            f"{source}: {len(matches)} files in {base_dir} match {reference!r} "
            f"({names}); keep exactly one"
        )
    return matches[0]


def check_suffix(path: Path, allowed: tuple[str, ...], *, source: str = "<config>") -> str:
    """The lower-cased suffix of ``path``, if this project can read that format."""
    suffix = path.suffix.lower()
    if suffix not in allowed:
        raise CVParseError(
            f"{source}: cannot read {path.name}: expected {' or '.join(allowed)}, got "
            f"{suffix or 'no extension'}"
        )
    return suffix


__all__ = [
    "CONFIG_SUFFIX",
    "MARKDOWN_SUFFIX",
    "SOURCE_SUFFIXES",
    "BuildConfig",
    "SectionSpec",
    "check_suffix",
    "load_config",
    "resolve_source",
]
