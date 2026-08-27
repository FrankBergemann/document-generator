# cv-generator

CLI that turns one Markdown file (YAML frontmatter + Markdown body) into a styled
CV as HTML, PDF or MS Word. See [README.md](README.md) for the source format and
usage.

## Commands

**Everything a human runs is a `.sh` script in [run/](run/)** — that is a design
rule, not a convenience. Documentation, CI and this file all invoke the same
scripts, so there is one place where "how you run it" is written down and it
cannot drift out of date. Adding a command means adding a script there; do not
document a bare `pytest`, `cv-generator …` or `docker compose …` line anywhere
else, and do not add a second wrapper mechanism (Makefile, `[project.scripts]`
entries beyond `cv-generator` itself, npm-style task runner).

Run them inside the dev container (Python 3.13, dependencies installed on
create), or in a local venv after `run/setup.sh`.

```bash
run/test.sh                     # tests
run/test.sh tests/test_word.py  # one file; arguments go to pytest
run/lint.sh                     # ruff check
run/format.sh                   # ruff format ('--check' to only report)
run/typecheck.sh                # mypy, strict, covers src/ and tests/
run/check.sh                    # all four, in CI's order
run/build.sh                    # data/cv.md -> dist/cv.html
run/build.sh -f pdf             # needs chromium, see below
run/build.sh -f docx
run/validate.sh
```

Conventions the scripts follow, worth keeping:

- Each one is a thin wrapper that forwards `"$@"`, so the CLI's own options keep
  working and there is no second argument parser to maintain.
- `run/build.sh` is the only one that does anything *after* the CLI: it copies the
  result to `dist/hist/<name>-<timestamp>.<ext>`. It learns the path it just
  archived by reading the CLI's own `wrote <path>` line, because the CLI is what
  resolves it (`-o`, else `dist/<source stem>.<format>`). Re-deriving that rule in
  bash would be a second source of truth that goes stale the moment the default
  changes -- so if you change what `build` prints on stdout, that parse is the
  thing that breaks.
- Shared logic lives in `run/_lib.sh`, sourced by every script: `set -euo
  pipefail`, `cd` to the project root resolved from `BASH_SOURCE` (so a script
  works from any directory), `cv_generator()` (console script, else `python -m
  cv_generator.cli`), `dev_tool()` (which reports the missing dev extra instead
  of "command not found", and never masks the tool's own exit code) and the
  compose paths.
- `[project.scripts]` still installs `cv-generator`, because a pip-installed copy
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
  `initializeCommand` does), and the compose project is named `cv-generator`
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
  mypy, ruff and pytest caches all land in `/tmp/cv-generator/`. So a root
  container (`run/verify-in-docker.sh`, CI) cannot drop anything into the tree in the
  first place, and there is nothing left in the repo for two users to fight over
  except `dist/`.

One `Permission denied` this does *not* explain: a file in `dist/` that is open
in Acrobat or Word on the host. Windows locks it, the mount reports EACCES, and
`stat` still shows `vscode`. Close the app.

## Architecture

```
                                          ┌─ render.py ─> HTML ─┬─> .html
cv.md ─────────── parser.py ─> CV model ──┤                     └─ pdf/chrome.py ─> .pdf
                     │         (pydantic) │
                     │                    └─ word.py ──────────────────────────────> .docx
*Projektliste*.docx ─┘
  "Projekthistorie"    docx_import.py
```

Each stage only knows the one before it. Adding an output format, a theme or a
CV section touches exactly one place.

## Conventions that matter here

- **Sections stay as Markdown in the model.** `CV.sections` is an ordered list of
  `Section(title, slug, markdown)`. Two things this rules out: per-section models
  for jobs/dates/skills (layout within a section belongs to the Markdown file and
  the theme), and pre-rendering to HTML (which would force `.docx` to parse HTML
  back into structure). Both backends consume
  [markdown.py](src/cv_generator/markdown.py), so enabling a Markdown feature
  there enables it everywhere at once — do not add a second parser instance.
- **The photo is loaded in the parser, and the model holds bytes.** `photo:` is
  the only frontmatter key naming another file; it is resolved relative to the
  `.md` and read by `parser.load_photo`, so `CV` is complete on its own and no
  backend touches the filesystem. That is what keeps the HTML self-contained (see
  below) and lets `.docx` embed the same image. Accepted formats are the
  intersection of what both backends handle — PNG, JPEG, GIF, sniffed from the
  content — so nothing can render in one output format and vanish from another.
- **Frontmatter rejects unknown keys** (`extra="forbid"` on every model). A typo
  in `cv.md` must fail loudly rather than be silently dropped. Keep it that way
  when adding fields.
- **Errors raised on purpose subclass `CVError`** ([errors.py](src/cv_generator/errors.py)).
  `cli.main` catches `CVError` and turns it into a one-line stderr message with
  exit code 1. Anything not worth that treatment should not be a `CVError`.
- **Trusted markup is wrapped in `Markup` in Python, never `| safe` in a
  template.** `render.py` wraps the stylesheet and the Markdown-derived HTML, so a
  theme author cannot accidentally escape CSS (`>` → `&gt;` breaks child
  selectors) or double-escape rendered Markdown. Autoescape stays on for
  everything from `cv.md`.
- **One section is imported, and it is the only exception to the rule above.**
  `## Projekte` is filled from the Word project list next to the CV, not from
  `cv.md`; see *The imported project list* below.
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

## The imported project list

`## Projekte` takes its content from the one `.docx` in the CV's directory whose
name contains "projektliste", section "Projekthistorie". The list is maintained
in Word and sent to clients from there, so Word is its source of truth and
retyping it as Markdown would create a second one. Everything about the
convention -- which section, which filename marker, which heading -- is three
constants at the top of [parser.py](src/cv_generator/parser.py); the mechanism is
[docx_import.py](src/cv_generator/docx_import.py).

The section's Markdown body is emptied on purpose (`markdown=""`), so no backend
can render both sources. `Section.blocks` and `Section.markdown` are never both
populated -- keep it that way, or a stale paragraph will surface in whichever
output format happens to prefer one over the other.

Four things that look arbitrary and are not:

- **The section's end is found by formatting, not by a style.** A hand-made Word
  CV has no `Heading 1` anywhere: its headings are bold, 12pt, no style at all.
  So the import stops at the next paragraph whose first run matches the
  `Projekthistorie` heading's *weight and size*. Colour is deliberately excluded
  -- in the real file the headings differ there.
- **Formatting is resolved, not read off the run.** Direct `rPr`, then the
  character style, then the paragraph style, each up its `basedOn` chain. The
  real bullets use a *heading* style and switch bold off run by run
  (`<w:b w:val="0"/>`), so reading only the direct properties makes them bold and
  reading only the style makes them huge. `None` means "not set here", `False` is
  a value.
- **Blank paragraphs are dropped between blocks and kept inside cells.** Between
  two tables they are Word's way of stopping the tables from merging; inside a
  cell they are the layout.
- **Word's `~$…` lock file is skipped in discovery.** It is a real `.docx` by
  name, so counting it would make every build fail while the list is open in
  Word -- exactly when someone is most likely to rebuild.

Font family, page setup and paragraph spacing are *not* imported: they stay the
CV's own, or the projects would drag a second document's design into the CV. In
`.docx` output the tables get Word's `Table Grid` and the source's column
proportions scaled to this page (`WordTheme.content_width_mm`); in HTML they get
`.cv-block-table` and `<col style="width:…%">`.

The fixture is *built*, not committed: `write_projektliste` in
[tests/support.py](tests/support.py) writes a document with the real one's shape
(bold 12pt headings, per-project tables, direct `numPr` bullets, a section before
and after the imported one). A committed `.docx` would be an opaque blob. Note
`data/cv.md` now needs `data/*Projektliste*.docx` to parse at all -- the test
that parses the repository sample fails without it.

## Word output specifics

`word.py` mirrors `templates/classic/cv.css` as a `WordTheme` dataclass, because
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
- The `projects_cv` fixture in [tests/conftest.py](tests/conftest.py) — a CV with
  a `## Projekte` section next to a generated project list. None of the files in
  `tests/data/` has such a section, which is what keeps the plain Markdown path
  covered; add one there and every one of those tests starts needing a `.docx`.
- `data/cv.md` is parsed by a test, so it must stay valid — including
  `data/photo.jpg`, which it references.

PDF assertions use `pypdf` to check real page geometry and extracted text rather
than only that a file appeared.
