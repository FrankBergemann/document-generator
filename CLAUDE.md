# document-generator

CLI that assembles a styled CV as HTML, PDF or MS Word from the files it is
written in: [data/config.json](data/config.json) lists, per section, the source
file, its `format`, and either the headlines bounding the span to copy (`.md`,
`.docx`) or the cell rectangle to copy (`.xlsx`). A single `.md` still builds on
its own, with no recipe. See [README.md](README.md) for the source format and
usage.

## Commands

**Everything a human runs is a `.sh` script in [run/](run/)** — that is a design
rule, not a convenience. Documentation, CI and this file all invoke the same
scripts, so there is one place where "how you run it" is written down and it
cannot drift out of date. Adding a command means adding a script there; do not
document a bare `pytest`, `document-generator …` or `docker compose …` line anywhere
else, and do not add a second wrapper mechanism (Makefile, `[project.scripts]`
entries beyond `document-generator` itself, npm-style task runner).

Run them inside the dev container (Python 3.13, dependencies installed on
create), or in a local venv after `run/setup.sh`.

```bash
run/test.sh                     # tests
run/test.sh tests/test_word.py  # one file; arguments go to pytest
run/lint.sh                     # ruff check
run/format.sh                   # ruff format ('--check' to only report)
run/typecheck.sh                # mypy, strict, covers src/ and tests/
run/check.sh                    # all four, in CI's order
run/build.sh                    # data/config.json -> dist/document.{html,docx,pdf}
run/build.sh -f html            # one format; -f is repeatable
run/build.sh -f pdf             # needs chromium, see below
run/build.sh -f docx
run/build.sh notes/talk.md      # a single .md, no recipe
run/build.sh --config other/config.json  # a different recipe, as a named flag
run/validate.sh                 # names the file behind each section
```

Conventions the scripts follow, worth keeping:

- Each one is a thin wrapper that forwards `"$@"`, so the CLI's own options keep
  working and there is no second argument parser to maintain.
- `run/build.sh` is the only one that does anything *after* the CLI: it copies each
  result to `dist/hist/<name>-<timestamp>.<ext>`. It learns the paths it just
  archived by reading the CLI's own `wrote <path>` lines -- one per format, since
  a `-f`-less build renders all of them -- because the CLI is what resolves them
  (`-o`, else `dist/<name>.<format>`, where the name comes from the recipe's
  `output` key and *not* from the recipe file, or every project would ship a
  `dist/config.html`). Re-deriving that rule in bash would
  be a second source of truth that goes stale the moment the default changes -- so
  if you change what `build` prints on stdout, that parse is the thing that
  breaks. It also keeps the CLI's exit code instead of letting `set -e` end the
  script: a build where only the PDF failed still wrote the other formats, and
  those are exactly what the archive is for.
- Shared logic lives in `run/_lib.sh`, sourced by every script: `set -euo
  pipefail`, `cd` to the project root resolved from `BASH_SOURCE` (so a script
  works from any directory), `cv_generator()` (console script, else `python -m
  cv_generator.cli`), `dev_tool()` (which reports the missing dev extra instead
  of "command not found", and never masks the tool's own exit code) and the
  compose paths.
- `[project.scripts]` still installs `document-generator`, because a pip-installed copy
  has no `run/` directory. The scripts prefer it when it is on PATH.

PDF tests skip themselves unless a browser is reachable — installed locally
(`run/setup.sh --pdf`) or served by the `playwright` container
(`run/browser-up.sh`). A green run with skips is not a green run of the PDF path;
get a browser before claiming PDF output works. `run/verify-in-docker.sh` is the
run that cannot skip them.

## The two containers

[.devcontainer/docker-compose.yml](.devcontainer/docker-compose.yml) runs Python
and Chromium as separate services on the external `common_network`, and
`pdf/chrome.py` connects to `ws://playwright:3000/` (`CV_GENERATOR_BROWSER_WS`)
instead of launching a browser. So: no browser, no browser system libraries and
no `playwright install` in the Python image, and the browser survives a dev
container rebuild.

Two things that will bite otherwise:

- **The network is external**, shared with neighbouring projects. It must exist
  before compose runs (`docker network create common_network`, which
  `initializeCommand` does), and the compose project is named `document-generator`
  explicitly — the default would be `.devcontainer`, which every project has.
- **Client and server versions must match**, or `connect()` fails on a version
  mismatch. `PLAYWRIGHT_VERSION` in `.devcontainer/.env` sets both the image tag
  and the pip pin; bump it in that one place. (`.env` is gitignored globally,
  with an exception for this one.)

To verify the whole thing outside VS Code — this is the run that actually
exercises the PDF path, with no browser in the Python container:

```bash
run/verify-in-docker.sh          # optional pytest arguments are forwarded
```

It starts the `playwright` service, waits for `Listening on` in its logs (`up -d`
returns before the server accepts connections), then runs the suite in a
throwaway `python:3.13-slim` container on `common_network` with
`CV_GENERATOR_BROWSER_WS=ws://playwright:3000/`. Two details in that script are
load-bearing: `--env-file .devcontainer/tool-caches.env`, because the container
runs as root (see below), and `playwright==$(PLAYWRIGHT_VERSION from .env)`,
because client and server must match. Without the websocket variable the same
command would run in local mode, where the PDF tests skip.

`run/browser-up.sh` and `run/browser-down.sh` are the same service on its own,
for a local venv on the host: `up` prints the `CV_GENERATOR_BROWSER_WS` line to
export, `down` stops the service rather than `compose down`, which would also
remove the dev container.

## One user writes into the workspace

The workspace is a Windows bind mount, and files a container creates in it are
owned by the creating user with mode 0755/0644. A directory written by root is
then unwritable by `vscode` — `run/test.sh`, `run/typecheck.sh` and
`run/build.sh` all fail
with `Permission denied` — and Windows cannot repair Linux ownership, so this is
a mess that outlives a container rebuild. Three guards:

- **`user: vscode` in the compose service.** Compose does not read the image's
  `remoteUser` metadata, so without this line the dev container runs as root;
  that is how the mess gets made. `devcontainer.json` repeats it as `remoteUser`,
  and `docker compose exec` needs no `-u` because of it.
- **`sudo chown -R vscode .` in `postCreateCommand`** repairs whatever an earlier
  root container already left behind. It takes under a second and is a no-op on a
  clean checkout. `rm` is not an alternative: deleting files inside a root-owned
  directory needs write permission on that directory.
- **Tool caches go outside the mount**, via
  [.devcontainer/tool-caches.env](.devcontainer/tool-caches.env) — `__pycache__`,
  mypy, ruff and pytest caches all land in `/tmp/document-generator/`. So a root
  container (`run/verify-in-docker.sh`, CI) cannot drop anything into the tree in the
  first place, and there is nothing left in the repo for two users to fight over
  except `dist/`.

One `Permission denied` this does *not* explain: a file in `dist/` that is open
in Acrobat or Word on the host. Windows locks it, the mount reports EACCES, and
`stat` still shows `vscode`. Close the app.

## Architecture

```
config.json ─── config.py ──┐            ┌─ render.py ─> HTML ─┬─> .html
  which span, which file    │            │                     └─ pdf/chrome.py ─> .pdf
document.md ──────────────────────┼ parser.py ─┤        (pydantic)
                            │  CV model  └─ word.py ──────────────────────────────> .docx
*Projektliste*.docx ────────┤
  "Projekthistorie"  docx_import.py
*.xlsx ──────────────────────┘
  a cell rectangle    xlsx_import.py
```

Each stage only knows the one before it. Adding an output format, a theme or a
CV section touches exactly one place — and a section is a line of JSON, not code.

`config.py` is the recipe's schema plus `resolve_source` (a `source` value → the
one file it names); `parser.py` is the only stage that reads source files, so the
backends see one finished model and never learn how many files went into it.
`load_doc(path)` is the single entry point both `build` and `validate` use: it
dispatches on the suffix (`.json` → recipe, else a lone `.md`) and returns the
Document together with the stem its outputs take. That stem is the recipe's
`output`, *not* the recipe file's name — `dist/config.html` would be nobody's
document.

## Conventions that matter here

- **Sections stay as Markdown in the model.** `document.sections` is an ordered list of
  `Section(title, slug, markdown)`. Two things this rules out: per-section models
  for jobs/dates/skills (layout within a section belongs to the Markdown file and
  the theme), and pre-rendering to HTML (which would force `.docx` to parse HTML
  back into structure). Both backends consume
  [markdown.py](src/cv_generator/markdown.py), so enabling a Markdown feature
  there enables it everywhere at once — do not add a second parser instance.
- **The photo is loaded in the parser, and the model holds bytes.** `photo:` is
  the only frontmatter key naming another file; it is resolved relative to the
  `.md` and read by `parser.load_photo`, so `Document` is complete on its own and
  no backend touches the filesystem. That is what keeps the HTML self-contained
  (see below) and lets `.docx` embed the same image. Accepted formats are the
  intersection of what both backends handle — PNG, JPEG, GIF, sniffed from the
  content — so nothing can render in one output format and vanish from another.
  A recipe with no Markdown source (or one whose Markdown source has no
  `photo:`) has no frontmatter to name a photo in, so `config.json`'s root-level
  `photo` key does the same job — see [The recipe](#the-recipe).
- **Frontmatter and `config.json` reject unknown keys** (`extra="forbid"` on every
  model, in [models.py](src/cv_generator/models.py) and
  [config.py](src/cv_generator/config.py) alike). A typo must fail loudly rather
  than be silently dropped — a mistyped recipe key would otherwise render a
  document with a section missing. Keep it that way when adding fields.
- **Errors raised on purpose subclass `DocError`** ([errors.py](src/cv_generator/errors.py)).
  `cli.main` catches `DocError` and turns it into a one-line stderr message with
  exit code 1. Anything not worth that treatment should not be a `DocError`.
- **Trusted markup is wrapped in `Markup` in Python, never `| safe` in a
  template.** `render.py` wraps the stylesheet and the Markdown-derived HTML, so a
  theme author cannot accidentally escape CSS (`>` → `&gt;` breaks child
  selectors) or double-escape rendered Markdown. Autoescape stays on for
  everything from `document.md`.
- **A `.docx`-sourced section is the only exception to the rule above.** It
  carries `blocks` instead of Markdown; see *Imported Word sections* below.
- **Composition lives in the recipe, never in the code.** Which section comes
  from which file is `config.json`'s business. There are no hard-coded section
  names, filename markers or headings left in `parser.py` — that is exactly what
  the three `PROJECTS_*` constants used to be, and generalising them away is why
  `config.py` exists. Do not add a "special" section back.
- **PDF page geometry belongs to the CSS, not the engine.** `chrome.py` passes
  `prefer_css_page_size` and zero margins so `@page` in the theme wins; otherwise
  the HTML preview and the PDF drift apart. If you change `@page`, re-check
  `test_pdf.py::TestChromePrinting`.
- **The rendered HTML must stay self-contained.** It is not only convenient, it
  is what makes the remote browser possible: the document crosses a websocket
  and the PDF comes back as bytes, so the browser never sees this filesystem. A
  theme referencing a local font or image would work locally and silently lose
  it in the container setup. For the same reason `page.pdf()` is called without
  `path=` — the file belongs on this side of the connection.
- **Word runs only ever switch formatting *on*.** Setting `run.font.bold = False`
  would override the paragraph style and un-bold every entry heading. See
  `WordRenderer._add_run`.
- **OOXML element order is load-bearing.** Word silently "repairs" documents whose
  XML children are out of schema sequence — invisible until a recruiter opens the
  file. All raw-XML work lives in [ooxml.py](src/cv_generator/ooxml.py), which
  handles ordering; keep new escape hatches there rather than in the renderer.
  It applies *inside* an element too, not only among its siblings: `w:tblCellMar`
  has to list top, left, bottom, right in that order. `test_word.py` asserts both
  kinds of ordering, because neither is visible in the output.

## The recipe

[config.py](src/cv_generator/config.py) is the schema; `parser.build_doc` is the
assembly. A `sections` entry copies one span of one file:

- **`format` says which reader parses `source`, and is required.** `"md"`,
  `"docx"` or `"xlsx"` — not guessed from `source`'s own suffix, because `source`
  may be a glob or a reissued file whose name is not a promise about its
  content. This is what `build_doc` switches on; it does not look at the resolved
  path's suffix at all.
- **An `"xlsx"` entry names a cell rectangle, not headlines.** `col-start`,
  `col-end`, `row-start` and `row-end` (a `SectionSpec` model validator requires
  all four together, and rejects all four for any other format) take the place
  of `begin`/`end` — a spreadsheet has no headings to bound a span with. Unlike
  `end` below, all four corners are **inclusive**, Excel's own convention. See
  [Imported Excel ranges](#imported-excel-ranges).
- **`end` is exclusive, for `.md` and `.docx`.** The span stops *before* that
  headline, so `end` names what comes next. Uniform on purpose — the natural
  reading differs between a `.md` (where a heading delimits a section) and a
  `.docx` (where it delimits an import), and two meanings for one key would be a
  trap. An `end` that never turns up is an error, not "run to the end of the
  file": the recipe stated where to stop, so importing the rest would put another
  section's content under this heading.
- **A Markdown span is split at its `##` headings; a `.docx` or `.xlsx` span is
  not.** Imported blocks and an imported rectangle have no headings to split at.
  That asymmetry is what lets three entries describe the five-section sample
  document.
- **`source` may be a glob, and then has to match exactly one file.** The real
  project list carries a date in its name, so a literal name goes stale every
  time it is reissued; that is what the old `find_docx` marker convention was for
  and `resolve_source` now generalises. Matching several is an error, not a pick
  — guessing would publish a CV built from last year's list. Word's `~$…` lock
  file never counts, or having the document open would break every build,
  exactly when someone is most likely to rebuild.
- **A plain (non-glob) `source` not found beside the config is tried again
  relative to the project root.** `resolve_source`'s `base_dir` (the config's own
  directory) wins when a file exists in both places, so this is a fallback, not a
  second meaning — a section may point at a file kept at the top of the project
  instead of beside the recipe that names it. The fallback does not apply to a
  glob. `build_doc`'s callers pass `project_root=Path.cwd()`, which is the project
  root by the same convention that makes the CLI's own default source
  (`data/config.json`) relative to it: `run/*.sh` all `cd` there first.
- **The `output` name comes from the recipe, not from the recipe file.** Every
  project's recipe is called `config.json`; `dist/config.html` would be nobody's
  document. `load_doc` returns the Document and that name together for this reason.
- **`target` picks the whole output path, not just the name, and is mutually
  exclusive with `output`.** A path relative to the project root, without an
  extension -- `"exports/lebenslauf"` becomes `exports/lebenslauf.html`, `.docx`,
  `.pdf` -- resolved the same way `source`'s project-root fallback is, against
  `Path.cwd()` by convention. `output` only ever renamed the file inside the
  fixed `dist/`; `target` subsumes that, so a `BuildConfig` validator rejects a
  recipe naming both, the same "two ways to say one thing" reasoning as
  `metadata` vs. an entry with no `begin`. `-o`/`--out` at the command line still
  wins over either, since it is the most specific override. `LoadedDocument.target`
  carries the resolved path (or `None`) from `build_doc` through to the CLI.
- **`title` never has to be given, and a `.docx`/`.xlsx` entry never falls
  back to its filename to invent one.** A missing `title` falls back to
  `begin` (the heading the span starts at) if there is one; with neither, the
  section renders with **no heading at all** (`Section.title = None`, and
  every renderer skips the heading) rather than one made of the source file's
  own name -- a filename names the file, not what a reader would call the
  content. This holds for every section, not just the document's first one.
  The slug still falls back to `path.stem` regardless: an anchor has to point
  *somewhere* even when nothing is shown for it.
- **No entry has to be Markdown.** A recipe built purely from `.docx`/`.xlsx`
  (an invoice, say) still assembles: `build_doc` falls back to a bare header
  (no name, headline, contact or summary) instead of raising, and the output
  stem falls back to `DEFAULT_NAME` (`"document"`) instead of a Markdown file's
  own stem -- `output`/`target` still override it the same way. `Document.name`
  is `str | None` for this reason; every renderer treats an absent name as "no
  header line" rather than crashing or printing the literal text `"None"`.
  `Document.has_identity()` (name, headline, contact or photo -- any one is
  enough) is what "no header line" means precisely: with nothing at all, both
  backends skip the header block entirely instead of rendering an empty one
  that still draws its own rule under nothing.
- **`photo` at the recipe's root is the non-Markdown equivalent of frontmatter's
  `photo:`.** Resolved the same way a section's `source` is (config directory,
  then project root). It wins over a Markdown-sourced photo when both are
  present, the same way `target` wins over a Markdown file's own stem -- one
  recipe, one photo, no guessing which one counts.
- **If the recipe's first entry is a `.docx`, its own page header *and*
  footer become `Document.page_header`/`page_footer`, exclusively.** Not the
  first `.docx` entry anywhere in the recipe -- specifically
  `config.sections[0]` -- and not whichever entry happens to carry a header or
  footer: one source of truth for both, so a document's page furniture is
  never stitched together from two different letterheads. This is unrelated to
  the *identity* header (name/headline/contact/photo), which may still come
  from a later, Markdown entry -- see :data:`DEFAULT_NAME` and
  `Document.has_identity`. `docx_import.load_header`/`load_footer` read them
  (see *Imported Word sections* below); `word.py` writes them back out as a
  real, repeating page header/footer, since that is what a `.docx` actually
  has. HTML/PDF have no such per-page concept, so there each renders once --
  the header at the top, the footer at the end of the (one, continuous)
  document.
- **Slugs are deduplicated across the whole document** (`_Slugger`), not per
  file. Two sources easily use the same heading, and slugs are the HTML anchors.

## Imported Word sections

A `.docx` entry's content arrives as `blocks` and its `markdown` is emptied on
purpose (`markdown=""`), so no backend can render both sources. `Section.blocks`
and `Section.markdown` are never both populated -- keep it that way, or a stale
paragraph will surface in whichever output format happens to prefer one over the
other. The mechanism is [docx_import.py](src/cv_generator/docx_import.py).

Three things that look arbitrary and are not:

- **Without an `end`, the section's end is found by formatting, not by a style.**
  A hand-made Word CV has no `Heading 1` anywhere: its headings are bold, 12pt,
  no style at all. So the import stops at the next paragraph whose first run
  matches the start heading's *weight and size*. Colour is deliberately excluded
  -- in the real file the headings differ there. A recipe that names an `end`
  overrules this guess; the fallback is what keeps a source with irregular
  headings usable at all.
- **Formatting is resolved, not read off the run.** Direct `rPr`, then the
  character style, then the paragraph style, each up its `basedOn` chain. The
  real bullets use a *heading* style and switch bold off run by run
  (`<w:b w:val="0"/>`), so reading only the direct properties makes them bold and
  reading only the style makes them huge. `None` means "not set here", `False` is
  a value.
- **Blank paragraphs are kept, not dropped.** A source document's own spacing
  is part of what it looked like -- between two tables it also happens to be
  Word's own way of stopping them from merging, but that is a side effect of
  keeping it, not the reason. `_section_of`/`load_section` no longer filter
  them out; `_is_blank` does not exist any more. A section entirely of blank
  paragraphs is not the same as no section -- see
  `TestSectionBoundaries::test_a_section_of_only_blank_paragraphs_is_not_empty`
  in [tests/test_docx_import.py](tests/test_docx_import.py).

Font family, page setup and paragraph spacing are *not* imported: they stay the
CV's own, or the projects would drag a second document's design into the document. In
`.docx` output the tables get Word's `Table Grid` and the source's column
proportions scaled to this page (`WordTheme.content_width_mm`); in HTML they get
`.cv-block-table` and `<col style="width:…%">`.

The fixture is *built*, not committed: `write_projektliste` in
[tests/support.py](tests/support.py) writes a document with the real one's shape
(bold 12pt headings, per-project tables, direct `numPr` bullets, a section before
and after the imported one). A committed `.docx` would be an opaque blob.

### The first entry's page header and footer

`docx_import.load_header`/`load_footer` are a second, separate way in -- not a
section's `blocks`, but `Document.page_header`/`page_footer` (see *The
recipe* above). Both share `_hdrftr_blocks` and the same three things about it
that are not obvious from a plain read of the OOXML:

- **A letterhead-style header/footer's real content usually lives inside an
  anchored text box, not a direct child paragraph of the part.**
  `w:txbxContent` paragraphs sit several levels below `w:hdr`/`w:ftr` --
  inside `w:r` → `mc:AlternateContent` → `w:drawing`/`w:pict` → the text box --
  so `_hdrftr_blocks` searches every paragraph under the part, at any depth,
  rather than only its top-level ones. The text box's own floating position is
  meaningless outside Word anyway, so flattening it into reading order loses
  nothing this project could have kept.
- **`mc:AlternateContent` holds two equivalent copies, and only one may be
  read.** `mc:Choice` is the modern DrawingML shape; `mc:Fallback` is a VML
  shape carrying the *same* text, for a Word too old to read the first. Word
  itself renders exactly one, so reading both would double every paragraph
  inside a text box -- `_hdrftr_blocks` skips a paragraph whose ancestor is
  `mc:Fallback`.
- **The first-page part is tried before the default one.** A short,
  single-page document -- an invoice, typically -- shows only its first-page
  header/footer; the "default" one, meant for a second page that never comes,
  is usually empty. Which of the two actually has content decides which
  `load_header`/`load_footer` return -- `_has_text`, not merely "did reading
  it produce any blocks at all": accessing `.paragraphs` on an undefined part
  creates one blank placeholder paragraph of its own, which would otherwise
  look like content and stop the fallback to the part that has the real thing.

Tables are not read here, unlike a section import -- a footer's own content is
plain paragraphs in every case this project has met, and `_Blocks` (the
protocol `word.py` writes through) has no `add_table`.

## Imported Excel ranges

An `"xlsx"` entry's content is a rectangle of cells, named by its corners
(`col-start`/`col-end`/`row-start`/`row-end`, all inclusive — see
[The recipe](#the-recipe)) rather than by headings, since a spreadsheet has none.
Like a `.docx` import it arrives as one `blocks` entry with `markdown=""`; unlike
one it is always exactly one `RichTable`, because there is nothing inside a
rectangle to split several blocks at. The mechanism is
[xlsx_import.py](src/cv_generator/xlsx_import.py).

Three things worth knowing before touching it:

- **Cells are read with `data_only=True`.** A formula cell's value is whatever
  Excel last calculated and cached into the file, not something this project
  recomputes. A workbook that has never been opened in Excel since a formula was
  entered has nothing cached, and that cell reads as empty — a property of
  `.xlsx` itself, not a bug here.
- **Number formatting is approximated, not interpreted.** Excel's format-code
  language covers locales, conditional sections and dozens of tokens; this
  module reads just enough of it for a CV-adjacent spreadsheet. A date or
  datetime becomes `DD.MM.YYYY` (the time of day, if any, is dropped); a format
  naming a currency symbol (€, $, £) becomes a two-decimal, German-grouped
  amount with that symbol (`1.275,00 €`); anything else is Python's own
  rendering of the value. `_format_number` and `_display_value` are the two
  functions to extend if another shape turns up.
- **Font colour is not carried over.** A cell's colour is usually a theme
  reference (`Color(theme=1, ...)`), not a literal RGB value, and resolving a
  theme means parsing `xl/theme1.xml`'s colour scheme — this module reads a
  literal `rgb` colour when a cell happens to have one and leaves it `None`
  otherwise, the same "direct value only, no chain to walk" limit `docx_import`
  accepts for character styles it cannot resolve.

Whether any cell in the rectangle carries a border decides `RichTable.bordered`
for the *whole* table — there is no per-cell border in the model, so this is a
coarser signal than Excel's own per-edge borders, the same simplification
`docx_import._is_bordered` makes for a `.docx` table's own ruling.

**`RichTable.centered` is always `True` for an `.xlsx` import, always `False`
for a `.docx` one.** A `.docx` table is meant to fill the page the way it did in
the source document -- that is what `column_widths` scaled to
`WordTheme.content_width_mm` (`.docx` output) or `<col style="width:…%">` inside
a `width:100%` table (HTML) already do. A spreadsheet range reads more like a
figure dropped into the page, so it is sized to its own content instead and
centered: `.cv-block-table--centered` (`width: auto; margin: … auto;`) in HTML,
and in `.docx` no explicit column widths are set at all -- Word's own default
`autofit` sizes each column to its content -- with `table.alignment =
WD_TABLE_ALIGNMENT.CENTER` (`word.py::_add_imported_table`). `column_widths` is
still populated for a centered table (it costs nothing to keep), but both
backends ignore it there; only `bordered` and the run-level formatting still
apply.

The fixture is *built*, not committed, for the same reason `write_projektliste`
is: `write_workbook` in [tests/support.py](tests/support.py) writes a workbook
with a bold, ruled header row and one data row (a date, a plain number, a
currency figure), plus content just outside the rectangle every test asks for —
the negative control for "the importer respected the corners it was given".

## Word output specifics

`word.py` mirrors `templates/classic/document.css` as a `WordTheme` dataclass, because
Word has no stylesheet. Content is applied through **named paragraph styles** so
the recipient can restyle from Word's style pane — do not hard-code run
formatting where a style would do.

Bullets use Word's built-in `List Bullet` / `List Number` styles (`_list_style`
degrades gracefully if a nesting level is missing from the template). `-t/--theme`
does not affect `.docx`.

A CV **with a photo** gets a different header: no flexbox in Word, so identity and
portrait go into a borderless one-row, two-column layout table, and the rule that
`.cv-header`'s `border-bottom` draws moves from the last paragraph to the table
(`add_table_bottom_border`) so it still spans the full width. Without a photo the
header is unchanged — both paths are covered, so check `TestHeaderPhoto` as well
as `TestHeader` when touching `_add_header`.

Gotcha when testing: `Paragraph.text` does **not** include runs inside a
`w:hyperlink`, so the contact line reads as mostly empty. Assert on
`document.element.xml` or on `document.part.rels` instead.

## Testing

`pytest`, class-per-unit, no mocking of the filesystem — tests use `tmp_path` and
the fixtures in [tests/conftest.py](tests/conftest.py). Shared helpers, including
the `requires_chromium` marker, live in [tests/support.py](tests/support.py).

- `tests/data/minimal.md` — the canonical small input.
- `tests/data/rich.md` — exercises every supported Markdown construct; extend
  this when adding one, so HTML and Word are both covered.
- `tests/data/photo.md` + `portrait.png` (120×160, so 3:4) — the photo path.
  Deliberately separate: `minimal.md` and `rich.md` stay photo-free so the
  photoless header keeps its coverage.
- The `projects_dir` / `projects_path` / `projects_cv` fixtures in
  [tests/conftest.py](tests/conftest.py) — a generated project list, a `document.md` and
  a `config.json` tying them together. `projects_path` is the *recipe*, which is
  what the CLI is handed. The `document.md` there keeps a `## Projekte` section no entry
  asks for, as the negative control: anything under it that reaches the output
  means a span was copied that nobody requested.
- Nothing in `tests/data/` has a recipe, which is what keeps the single-`.md` path
  covered. Add one there and those tests start needing a `.docx`.
- `data/document.md` and `data/config.json` are both exercised by a test, so they must
  stay valid — including `data/photo.jpg` and `data/Rechnungsbeträge.xlsx`, the
  workbook the recipe's `"xlsx"` entry names.

PDF assertions use `pypdf` to check real page geometry and extracted text rather
than only that a file appeared.
