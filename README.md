# document-generator

Generate a file with content from a number of source files. A short
[`data/config.json`](data/config.json) says which section comes from where — a
span of a Markdown file, a section of a Word document, or a cell rectangle from
an Excel workbook — and the tool produces one styled, print-ready document as
**HTML**, **PDF** or **MS Word (.docx)**.

## Everything you run lives in `run/`

Every command this project asks you to type is a script in [run/](run/), with a
`.sh` extension. There is nothing to remember beyond the directory listing:

| Script | What it does |
|---|---|
| [run/setup.sh](run/setup.sh) | Editable install with the dev extra; `--pdf` adds a local Chromium |
| [run/build.sh](run/build.sh) | Render the CV — every format, or `-f html\|pdf\|docx` (`-o`, `-t`, …) |
| [run/validate.sh](run/validate.sh) | Assemble and report which file fed which section, write nothing |
| [run/themes.sh](run/themes.sh) | List HTML/PDF themes |
| [run/engines.sh](run/engines.sh) | PDF engine status, including the browser server |
| [run/browser-up.sh](run/browser-up.sh) | Start the Chromium container and wait for it |
| [run/browser-down.sh](run/browser-down.sh) | Stop it again |
| [run/test.sh](run/test.sh) | `pytest`, arguments passed through |
| [run/lint.sh](run/lint.sh) · [run/format.sh](run/format.sh) · [run/typecheck.sh](run/typecheck.sh) | ruff check, ruff format, mypy |
| [run/check.sh](run/check.sh) | All four, in CI's order |
| [run/verify-in-docker.sh](run/verify-in-docker.sh) | The suite in a browser-less container, against the Chromium one |

Each script is a thin wrapper that forwards its arguments, so anything the CLI
accepts still works — `run/build.sh input/other.md -f pdf -o out/other.pdf`. The
shared bits live in `run/_lib.sh`, which is sourced rather than executed.

A script works from any directory: it finds the project root itself and runs
there, so `data/document.md`, `dist/` and every other relative path mean the same thing
wherever you invoke it from — including path arguments, which are read relative to
the project root rather than your shell's directory. Absolute paths are absolute.

`pip install`ing the package still puts a `document-generator` command on PATH; the
scripts prefer it and fall back to `python -m cv_generator.cli`.

They are bash scripts, which the dev container and CI have. On a Windows host use
Git Bash or WSL — `bash run/build.sh -f docx` works from PowerShell too.

## Setup

Development happens in the dev container: two containers side by side, Python in
one and Chromium in the other.

```bash
docker network create common_network      # once per machine, see below
# VS Code: "Dev Containers: Reopen in Container"
# Dependencies are installed by postCreateCommand; the browser needs no install.
```

Or locally, with any Python ≥ 3.11:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
run/setup.sh
```

HTML and `.docx` work out of the box. PDF needs a browser — either installed
next to the interpreter (a ~150 MB download, therefore opt-in):

```bash
run/setup.sh --pdf             # pip install -e ".[dev,pdf]" + playwright install chromium
run/engines.sh                 # confirms: chrome [ready]
```

…or supplied by a container, with nothing to download but the pip package:

```bash
run/browser-up.sh              # starts the playwright service, prints the next line
export CV_GENERATOR_BROWSER_WS=ws://localhost:3000/   # PowerShell: $env:CV_GENERATOR_BROWSER_WS=...
run/engines.sh                 # names the browser server and confirms: chrome [ready]
```

### The two containers

[.devcontainer/docker-compose.yml](.devcontainer/docker-compose.yml) runs the
Python image and the official Playwright image as separate services on a shared
Docker network, and `pdf/chrome.py` connects to the browser over a websocket
instead of launching one locally:

```
document-generator (python:3.13)  ──ws://playwright:3000/──>  playwright run-server
                            <──────  PDF bytes  ──────  (Chromium, noble)
```

- The Python image stays a plain Python image: no browser, no browser system
  libraries, no `playwright install` on container create.
- Both images pull and start in parallel, and the browser survives a dev
  container rebuild because it is a separate service.
- `common_network` is `external`, so it is shared with other projects — a
  browser server started by a neighbouring dev container is reachable by name
  from this one too. It has to exist first: `docker network create common_network`.
- Client and server versions must match. `PLAYWRIGHT_VERSION` in
  [.devcontainer/.env](.devcontainer/.env) is the single place to bump: it picks
  both the image tag and the pip pin.

`CV_GENERATOR_BROWSER_WS` is the whole interface. Unset (or empty) means "launch
a local browser", so nothing about local development changes.

### Everything in the workspace is written by one user

The dev container runs as `vscode` (`user:` in the compose service, `remoteUser`
in `devcontainer.json`). That matters because the workspace is a bind mount:
files a root container creates in it are root-owned and mode 0755, `vscode` then
cannot write them, and Windows cannot repair Linux ownership. So `postCreateCommand`
starts with `sudo chown -R vscode .` to clean up after any earlier root container,
and tool caches (`__pycache__`, mypy, ruff, pytest) are redirected to
`/tmp/document-generator/` by [.devcontainer/tool-caches.env](.devcontainer/tool-caches.env)
so they never land in the repo at all.

If a build reports `Permission denied` on a file in `dist/`, check whether Acrobat
or Word has it open on the host — Windows locks the file and the mount reports it
as a permission error.

## Usage

```bash
run/build.sh                     # data/config.json -> dist/document.html, .docx, .pdf
run/build.sh -f html             # -> dist/document.html
run/build.sh -f pdf              # -> dist/document.pdf
run/build.sh -f docx             # -> dist/document.docx
run/build.sh -f html -f docx     # a subset; -f is repeatable
run/build.sh -o out.pdf
run/build.sh -t classic          # theme (HTML/PDF only)
run/build.sh other/config.json   # a different recipe
run/build.sh --config other/config.json  # the same, as a named flag
run/build.sh notes/talk.md       # a single Markdown file, no recipe
run/validate.sh                  # assemble and report, write nothing
run/themes.sh
run/engines.sh
```

The source argument is a build recipe (`.json`) or a single Markdown file, told
apart by the suffix, so both fit one argument and neither needs a flag.

With no `-f` you get all three, in the order `html`, `docx`, `pdf`: the same CV
usually goes out as a PDF and is kept as a `.docx`, so rendering the set is the
normal run and picking one the exception. Each format is written independently —
with no browser reachable the `.html` and `.docx` are still produced, the PDF's
error goes to stderr, and the exit code is non-zero. `-o` names a single file, so
it takes a single format: from `-f`, or from the extension you gave it.

Every build overwrites its target in `dist/` without asking, so the current
result is always at the same path, and copies it to
`dist/hist/<name>-<YYYYmmdd-HHMMSS>.<ext>` so the replaced one stays
recoverable. The timestamp sits before the extension, so an archived copy still
opens in the same application as the original. `dist/` is gitignored, history
included; prune `dist/hist/` whenever you like — nothing reads it back.

## The source format

Markdown: YAML frontmatter for identity and contact details, Markdown below for
content. Any number of such files supply the sections, as [the
recipe](#the-recipe) below decides; the frontmatter of whichever one a span
starts at the *top* of becomes the CV's header.

```markdown
---
name: Frank Bergemann
headline: Senior Software Engineer
lang: de                       # also sets Word's spell-check language
theme: classic                 # HTML/PDF only
photo: photo.jpg               # optional; PNG, JPEG or GIF
contact:
  email: frank.bergemann@gmx.de
  phone: "+49 ..."
  location: Deutschland
  links:
    - label: GitHub
      url: https://github.com/...
---

Optional summary. Everything before the first `##` goes here.

## Berufserfahrung

### Senior Software Engineer — Beispiel GmbH
*2021 – heute · Remote*

- One achievement per bullet, with a number where you have one.
```

Rules:

| Element | Meaning |
|---|---|
| Frontmatter | Header data. Unknown keys are rejected, so typos fail loudly. |
| `photo:` | Portrait for the header, top right. Path relative to the `.md` file. |
| Text before the first `##` | Summary paragraph. |
| `##` | A section (Experience, Skills, Education, …). Order is preserved. |
| `###` | One entry within a section: a role, a degree, a project. |
| `*italic line*` right after a `###` | Styled as the entry's date/location line. |
| Everything else | Plain Markdown — lists (nested too), bold, italic, strikethrough, inline code, fenced code, links, blockquotes, tables, rules. |

Section names are free-form: rename, reorder or drop them and every output
format follows.

## The recipe

A CV, for example, can have content from several other files. The prose is written in Markdown, but the project list
is maintained in Word and sent to clients from there, so Word stays *its* source
of truth — retyping it as Markdown would create a second one and lose the layout
besides. [`data/config.json`](data/config.json) is where that composition is
written down, and it is the whole of it:

```json
{
  "sections": [
    { "source": "document.md",           "format": "md",                     "end": "Kenntnisse" },
    { "source": "Rechnungsbeträge.xlsx", "format": "xlsx", "col-start": "C", "col-end": "G",
      "row-start": 3, "row-end": 15, "title": "Rechnungsbeträge" },
    { "source": "document.md",           "format": "md",   "begin": "Kenntnisse" }
  ]
}
```

```
data/
  config.json                the recipe above
  document.md                header + Berufserfahrung, Kenntnisse, Ausbildung, Sprachen
  Rechnungsbeträge.xlsx      C3:G15, one invoice's line items
  photo.jpg
```

Three entries, five sections: Berufserfahrung, **Rechnungsbeträge** (from
Excel), Kenntnisse, Ausbildung, Sprachen. Edit either file, rebuild, and the CV
follows. (An earlier version of this same recipe imported a project list from a
`.docx` the same way — see `format` below; the mechanism is the same for both.)

| Key | Meaning |
|---|---|
| `sections` | One entry per span, concatenated in the order listed. The only key a recipe needs. |
| `source` | A file in the recipe's own directory, or (if not found there) relative to the project root. May be a glob — `*Projektliste*.docx` survives the list being reissued with a new date in its name — and then has to match exactly one file; the project-root fallback does not apply to a glob. |
| `format` | Which reader parses `source`: `md`, `docx`, or `xlsx`. Required, and not guessed from `source`'s suffix — a glob or a reissued file's name is not a promise about its content. |
| `begin` | The headline the span starts at (`.md`/`.docx` only) — a regular expression, matched case-insensitively and in full (plain text matches itself exactly), with or without its `##`. **Leave it out** and the span starts at the top of the file. |
| `end` | The headline it stops **before** (`.md`/`.docx` only), matched the same way — that headline belongs to whatever comes next and is not copied. **Leave it out** and the span runs to the end of the file. An `end` that never turns up is an error, not "run to the end": the recipe said where to stop. |
| `col-start` / `col-end` / `row-start` / `row-end` | The cell rectangle to copy (`xlsx` only), Excel's own way — column letters and 1-based row numbers, **both ends inclusive**. Required together; rejected for any other `format`. |
| `noframes` | `true`/`false` (`xlsx` only, rejected for any other `format`) — draw the imported table without cell borders regardless of what the workbook itself has. **Leave it out** (or `false`) and whether any cell in the range is ruled still decides it, same as before this key existed. |
| `title` | Renames a `.docx`/`.xlsx` span's section. Never required: falls back to `begin` (the heading it starts at) if there is one. With neither, the section shows **no heading at all** — a filename is not a title, and this holds for every section, not just the first — a Markdown span already takes its titles from its own `##` headings and is never affected. |
| `output` | The stem the results take: `dist/document.html`, `dist/document.docx`, `dist/document.pdf`. Defaults to that of the file the header came from — `document.md`, hence `dist/document.*`. Mutually exclusive with `target`, which also picks the directory. |
| `target` | Where the results go **and** what they're called, relative to the project root and with no extension — `"exports/lebenslauf"` becomes `exports/lebenslauf.html`, `.docx`, `.pdf`. Use this instead of `output` when the results shouldn't land in `dist/`. `-o`/`--out` still overrides either. |
| `photo` | A portrait image, resolved the same way `source` is. The non-Markdown equivalent of frontmatter's `photo:` key — use it when the recipe has no Markdown source, or its Markdown source has none of its own. Wins over a Markdown-supplied photo when both are present. |

If the recipe's **first** entry is a `.docx` (specifically the first one, not just the first `.docx` anywhere in the recipe), that one file's own page header *and* footer are both carried over as the target document's page header and footer — exclusively, so the result is never stitched together from two different letterheads. A letterhead-style first page often carries a running header (name, page numbers) and a footer (address, bank details) that are otherwise nowhere a recipe could name. `.docx` output gets a real, repeating page header/footer; HTML/PDF have no such per-page concept, so there each appears once — the header at the top, the footer at the end.

Blank lines from a `.docx` source — in a section, a page header or a page footer — are kept, not dropped: the source document's own spacing is part of what it looked like.

### Where the header comes from

There is no key naming a metadata file. **A span that starts at the top of a
Markdown file brings the header with it** — frontmatter is part of the beginning
of a document, so the first entry with no `begin` is where `name`, `headline`,
`contact`, `photo` and the summary come from. Above, that is the first entry,
which supplies the header *and* Berufserfahrung.

To take a file's header and none of its sections, end at its first heading:

```json
{ "source": "document.md", "format": "md", "end": "Berufserfahrung" }
```

A later entry that also starts at the top contributes only its sections: the CV
has one name and one summary, and the first entry to supply them is the one that
does. **No entry has to be Markdown at all** — a recipe built purely from
`.docx`/`.xlsx` (an invoice, say) still builds, just with a bare header: no
name, headline, contact or summary, and `dist/document.*` unless `output` or
`target` says otherwise. A photo, if it wants one, comes from the root-level
`photo` key instead of frontmatter (see [The recipe](#the-recipe) above). With
nothing in it at all — no name, headline, contact or photo — the header itself
is left out of the result, rather than rendering as an empty block with a rule
drawn under nothing.

### Spans

A **Markdown span is split at its own `##` headings**, the way a single-file CV
is, so the third entry above contributes three sections, each with its own
heading and anchor. A **`.docx` or `.xlsx` span is one section**: imported
blocks and an imported cell rectangle have no headings of their own to split at.
Titling it never needs a `title` key: a `.docx` entry falls back to `begin`
(the heading it starts at) if there is one, and either format falls back to the
source file's own stem — `title` is only for when neither reads well.

Unknown keys are rejected, so a typo fails loudly rather than silently dropping a
section. A file may be used any number of times, and the spans need not be in the
source's own order.

Nothing is lost by leaving the recipe out: `run/build.sh notes/talk.md` renders a
single Markdown file as its own header and sections, as before.

### What an imported Word section keeps

| | |
|---|---|
| Which part of it | From `begin` to `end`. Without an `end`, to the next paragraph formatted like the heading it started from (same weight, same size) — a hand-made Word CV has no heading *styles* to go by. Without a `begin` there is no shape to compare against either, so the span runs to the `end`, or to the last page if there is none. |
| Zero or several files match | An error naming them. Guessing would quietly publish a CV built from last year's list. Word's `~$…` lock file never counts, so an open document does not break the build. |
| Kept | Bold, italic, underline, strikethrough, size, colour, hyperlinks, bullets and their nesting, table columns and widths, whether the table is ruled, and a picture a run carries (inline or floating, either way — its own size and position are not, only the image itself). |
| Not kept | Font family, page setup, paragraph spacing — those stay the CV's own, so the imported projects sit in this document rather than importing a second design. |

### What an imported Excel range keeps

| | |
|---|---|
| Which part of it | The rectangle `col-start`/`row-start` to `col-end`/`row-end`, **both ends inclusive** — Excel's own addressing, not the exclusive `end` above. A blank row or column inside it stays, since it is part of the grid, not spacing between blocks. |
| Cell values | The value Excel last calculated and cached (`data_only` reading) — a formula cell in a workbook that has never been reopened in Excel since editing has nothing cached and reads empty. A date becomes `DD.MM.YYYY`; a format naming a currency symbol (€, $, £) becomes a two-decimal, thousands-grouped amount with that symbol; anything else renders in Excel's general style. This is an approximation of Excel's number-format language, not an implementation of it. |
| Kept | Bold, italic, underline, strikethrough, font size, and whether any cell in the range is ruled (one flag for the whole table, not per edge). |
| Layout | Sized to its own content and **centered**, unlike an imported Word section, which fills the page. The sheet's own column *widths* are read but not used for this reason — there is no page-width table for their proportions to describe. |
| Not kept | Font family and page layout, for the same reason as a Word import — and a cell's colour when it is a theme reference rather than a literal RGB value, which is most of them. |

`run/validate.sh` prints which file fed which section, which is the thing to
check before a build goes out — a recipe resolves globs and headlines, and
neither is visible in the result:

```
data/config.json: ok - Frank Bergemann, 5 section(s) -> document.*
  photo: image/jpeg, 680 kB
  - Berufserfahrung (berufserfahrung) <- data/document.md
  - Rechnungsbeträge (rechnungsbetrage) <- 1 block(s) from data/Rechnungsbeträge.xlsx
  - Kenntnisse (kenntnisse) <- data/document.md
  - Ausbildung (ausbildung) <- data/document.md
  - Sprachen (sprachen) <- data/document.md
```

All three output formats show the same imported content: HTML and PDF render the
tables with the source's widths, `.docx` writes them as real Word tables with
Word's own bullet styles.

## How it fits together

```
data/config.json ─── config.py ──┐            ┌─ render.py ─> HTML ─┬─> .html
  which span, which file         │            │                     └─ pdf/chrome.py ─> .pdf
data/document.md ──────────────────────┼ parser.py ─┤        (pydantic)
  frontmatter + Markdown         │ Document model └─ word.py ─────────────────────────> .docx
*Projektliste*.docx ─────────────┤
  "Projekthistorie"   docx_import.py
*.xlsx ───────────────────────────┘
  a cell rectangle    xlsx_import.py
```

- [src/cv_generator/config.py](src/cv_generator/config.py) — the recipe's schema, and resolving a `source` to one file
- [src/cv_generator/parser.py](src/cv_generator/parser.py) — the source files → model
- [src/cv_generator/models.py](src/cv_generator/models.py) — the validated `Document` schema
- [src/cv_generator/markdown.py](src/cv_generator/markdown.py) — the one Markdown parser both backends share
- [src/cv_generator/docx_import.py](src/cv_generator/docx_import.py) — a Word section → blocks in the model
- [src/cv_generator/xlsx_import.py](src/cv_generator/xlsx_import.py) — a cell rectangle → blocks in the model
- [src/cv_generator/render.py](src/cv_generator/render.py) — model → self-contained HTML
- [src/cv_generator/word.py](src/cv_generator/word.py) — model → `.docx` (see `WordTheme`)
- [src/cv_generator/ooxml.py](src/cv_generator/ooxml.py) — the OOXML bits python-docx has no API for
- [src/cv_generator/pdf/](src/cv_generator/pdf/) — the `PdfEngine` protocol and the Chromium engine
- [src/cv_generator/templates/](src/cv_generator/templates/) — HTML themes (`document.html.j2` + `document.css`)

**The photo is read by the parser, not by the backends.** `photo:` is the one
frontmatter key naming another file, resolved relative to the `.md` so a CV and
its portrait travel together; `config.json`'s root-level `photo` key does the
same job for a recipe with no Markdown source of its own. The model then
carries the *bytes*, which is what lets the HTML stay self-contained and the
`.docx` embed the image, with neither output stage touching the disk. Only
formats both backends understand are accepted — PNG, JPEG and GIF, sniffed from
the content rather than trusted from the extension — so a photo cannot render in
one format and silently vanish from another.

**Sections stay as Markdown in the model.** Not as a rigid schema of jobs and
dates, so the Markdown file rather than the model decides how a section is laid
out — and not as pre-rendered HTML, because `.docx` would then have to parse HTML
back into structure. Both backends consume the same syntax tree, so a Markdown
feature is either supported by both or visibly missing from both.

**Except an imported section, which carries blocks.** Markdown cannot express a
two-column table with a bullet list in one cell, and pre-rendered Word XML would
leave HTML nothing to work with, so `docx_import.py` reduces the Word section to
a small neutral tree of paragraphs, runs and tables. Same rule as for Markdown:
both backends read it, so neither can drift ahead of the other. Word formatting
is *resolved* while reading — direct on the run, else the character style, else
the paragraph style, following each `basedOn` — because real documents lean on
all three at once.

## PDF

Rendered by headless Chromium via Playwright, so what you see previewing the
HTML in a browser is what lands in the PDF.

The browser runs in this process or in another container, chosen by
`CV_GENERATOR_BROWSER_WS` alone (see [Setup](#the-two-containers)) — one code
path either way. Remote mode works because the renderer produces a
*self-contained* document: the HTML crosses the websocket and the PDF comes back
as bytes, so the browser never reads this filesystem. That is a reason to keep
themes free of external references; a local font file would render here and
vanish there.

Page geometry lives in the stylesheet (`@page { size: A4; margin: 16mm 15mm }`),
not in the engine: `page.pdf()` is called with `prefer_css_page_size` and zero
margins so Chromium's own defaults cannot quietly override the theme.

With no browser reachable, `--format pdf` fails with instructions — how to
install one, or how to start the container it was told to use — rather than a
traceback. The fallback is `--format html` plus browser print-to-PDF, which uses
the same `@page` rules and produces near-identical output.

`run/engines.sh` also documents WeasyPrint and LaTeX, which were
considered and not built, with their trade-offs.

## MS Word

`--format docx` produces a real Word document, not an HTML file with a `.docx`
extension:

- **Named paragraph styles** (`CV Name`, `CV Section Heading`, `CV Entry`, …), so
  the recipient can restyle the whole document from Word's style pane instead of
  reformatting paragraph by paragraph.
- Word's own **list styles** for bullets and numbers, including nesting.
- Real **hyperlinks** for the email address and every link.
- **Tables**, fenced code, blockquotes and horizontal rules.
- An **imported `.docx` section or `.xlsx` range** as real Word tables: the
  source's column proportions scaled to this page, its runs' weight, size and
  colour, and (for `.docx`) Word's own bullet styles.
- The **photo**, embedded in the document, placed by a borderless layout table
  because Word has no flexbox: identity left, portrait against the right margin.
- A4 page setup, `keep-with-next` on headings so no entry title is orphaned at a
  page break, and the document language tagged for spell-check.

Word has no stylesheet, so the visual choices of `templates/classic/document.css` are
mirrored in `WordTheme` ([word.py](src/cv_generator/word.py)). Themes given with
`-t` apply to HTML and PDF only; to restyle `.docx`, pass a `WordTheme`:

```python
from pathlib import Path
from cv_generator import WordRenderer, WordTheme, load_doc

doc, name, target = load_doc(Path("data/config.json"))  # or a plain .md
theme = WordTheme(body_font="Georgia", accent="7A2E2E")
WordRenderer(theme).render(doc, Path(f"dist/{name}.docx"))
```

Not supported: images inside section Markdown (the header photo is; `![...]()`
in a section body falls back to its alt text).

## Adding a theme

Copy `src/cv_generator/templates/classic/` to a new directory next to it. A theme
is exactly two files, `document.html.j2` and `document.css`. Keep both branches of the
section loop — `section.blocks | blocks` as well as `section.markdown | markdown`
— or an imported section renders as an empty heading. Then:

```bash
run/build.sh -t your-theme
```

Themes can also live outside the package: `--templates-dir ./my-themes`.

## Adding a PDF engine

1. Write a class in `src/cv_generator/pdf/` satisfying the `PdfEngine` protocol
   (`is_available()` and `render(html, output)`).
2. Register it in `_FACTORIES` in
   [registry.py](src/cv_generator/pdf/registry.py).
3. Add the runtime dependency to `pyproject.toml` as an optional extra.

Nothing else changes — the parser, model, templates and CLI are already wired.

## Development

```bash
run/test.sh              # tests; PDF tests skip when Chromium is absent
run/lint.sh              # ruff check
run/format.sh            # ruff format
run/typecheck.sh         # mypy, strict
run/check.sh             # all of the above, as CI runs them
run/verify-in-docker.sh  # the PDF path for real: no browser here, one over there
```

`run/test.sh` passes its arguments to pytest (`run/test.sh tests/test_word.py -k
photo`), and the same holds for the three tool wrappers.
