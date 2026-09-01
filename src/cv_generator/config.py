"""The build recipe: which sections the target document has, and where each comes from.

A CV is normally assembled from more than one file. The prose is written in
Markdown, but a project list is maintained in Word and sent to clients from
there, so Word stays its source of truth; a second CV may reuse the same project
list with a different summary. ``config.json`` is where that composition is
written down::

    {
      "sections": [
        {"source": "document.md",   "format": "md",                       "end": "Kenntnisse"},
        {"source": "Rechnungsbeträge.xlsx", "format": "xlsx", "col-start": "C", "col-end": "G",
         "row-start": 3, "row-end": 15, "title": "Rechnungsbeträge"},
        {"source": "document.md",   "format": "md",         "begin": "Kenntnisse"}
      ]
    }

Every entry copies one span out of one source file, and the spans are
concatenated in the order they are listed. A file may be used any number of
times, and the spans need not be in the source's own order.

Five rules decide what a span *is*:

* **``format`` says which reader parses ``source``, and is required.** It is not
  guessed from ``source``'s own suffix, because ``source`` may be a glob or a
  reissued file whose name is not a promise about its content -- stating the
  format is what lets dispatch be exact instead of a guess.
* **An ``"xlsx"`` entry names a cell rectangle instead of headlines.** There are
  no headings in a spreadsheet to begin or end at, so ``col-start``, ``col-end``,
  ``row-start`` and ``row-end`` take the place of ``begin``/``end`` -- Excel's own
  addressing, both ends inclusive, unlike the exclusive ``end`` below. See
  :mod:`cv_generator.xlsx_import` for what "keeping the formatting" means for a
  spreadsheet.
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
  sections; a ``.docx`` or ``.xlsx`` span is one section, since neither imported
  blocks nor a cell rectangle carry headings of their own. That is what lets
  three entries describe a five-section document.

``source`` is resolved relative to this file's own directory, so a config and the
files it names travel together. It may be a glob -- ``*Projektliste*.docx``
matches a list whose name carries a date, which a literal name would not survive
-- and then has to match exactly one file: picking one of several would quietly
publish a CV built from last year's list.

A plain (non-glob) ``source`` that is not found beside the config is also tried
relative to the project root, so a section may point at a file kept at the top
of the project (``data/document.md``) instead of beside the recipe that names
it. The config's own directory is tried first, so a file that exists in both
places is not ambiguous.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cv_generator.docx_import import LOCK_PREFIX
from cv_generator.errors import CVParseError

CONFIG_SUFFIX = ".json"

# What a section's `source` is read as. Distinct from the CLI's own --format,
# which names an *output* (html/docx/pdf); this one names the reader a span is
# parsed by, and is what dispatch in `parser.build_cv` switches on.
SourceFormat = Literal["md", "docx", "xlsx"]

# Only these make a value a pattern. Everything else is a plain relative path, so
# a file really named "cv (2).md" is not accidentally read as a glob.
_GLOB_CHARS = "*?["


class SectionSpec(BaseModel):
    """One span of one source file, copied into the target document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str
    # Required rather than guessed from `source`'s suffix: `source` may be a
    # glob, and a guess would silently do the wrong thing for a file whose name
    # does not match its content.
    format: SourceFormat
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
    # The rectangle an "xlsx" entry reads, Excel's own way: column letters and
    # 1-based row numbers, both ends inclusive. Hyphenated in the recipe because
    # every other key here is a plain word and these four are a related group;
    # `populate_by_name` still allows the Python-shaped name in code.
    col_start: str | None = Field(default=None, alias="col-start")
    col_end: str | None = Field(default=None, alias="col-end")
    row_start: int | None = Field(default=None, alias="row-start")
    row_end: int | None = Field(default=None, alias="row-end")

    @model_validator(mode="after")
    def _rectangle_matches_format(self) -> SectionSpec:
        """The four corners are required together for "xlsx" and meaningless otherwise.

        Half a rectangle is not a smaller rectangle, and a corner given for a
        `.md` or `.docx` entry would silently do nothing -- both are typos worth
        failing loudly over, the same reason an unknown key is rejected.
        """
        corners = (self.col_start, self.col_end, self.row_start, self.row_end)
        if self.format == "xlsx":
            if any(corner is None for corner in corners):
                raise ValueError(
                    "an 'xlsx' entry needs 'col-start', 'col-end', 'row-start' and "
                    "'row-end' to name the rectangle to read"
                )
        elif any(corner is not None for corner in corners):
            raise ValueError(
                "'col-start', 'col-end', 'row-start' and 'row-end' only apply to format 'xlsx'"
            )
        return self


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


def resolve_source(
    base_dir: Path,
    reference: str,
    *,
    source: str = "<config>",
    project_root: Path | None = None,
) -> Path:
    """Turn a ``source`` value into the one file it names.

    A value with no glob character in it is a plain path, relative to
    ``base_dir`` unless it is absolute. If it is not found there and
    ``project_root`` is given, the same relative path is tried again there --
    ``base_dir`` wins when both exist, so a file present in both places is not
    ambiguous. A value with a glob character is matched against ``base_dir``
    only (``project_root`` does not apply to a pattern) and has to hit exactly
    one file; Word's ``~$…`` lock file never counts, or having the document
    open would break every build -- exactly when someone is most likely to
    rebuild.

    Raises:
        CVParseError: if the value is empty, names a file that is not there, or
            is a pattern matching no file or several.
    """
    reference = reference.strip()
    if not reference:
        raise CVParseError(f"{source}: a source must name a file, got an empty string")

    if not any(char in reference for char in _GLOB_CHARS):
        path = Path(reference)
        if path.is_absolute():
            if not path.is_file():
                raise CVParseError(f"{source}: no such file: {path}")
            return path
        candidate = base_dir / path
        if candidate.is_file():
            return candidate
        if project_root is not None and project_root != base_dir:
            root_candidate = project_root / path
            if root_candidate.is_file():
                return root_candidate
        raise CVParseError(f"{source}: no such file: {candidate}")

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


__all__ = [
    "CONFIG_SUFFIX",
    "BuildConfig",
    "SectionSpec",
    "SourceFormat",
    "load_config",
    "resolve_source",
]
