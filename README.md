# cv-generator

Generate a CV from a single Markdown file. You edit one `.md`, the tool produces
a styled, print-ready document as **HTML**, **PDF** or **MS Word (.docx)**.

## Everything you run lives in `run/`

Every command this project asks you to type is a script in [run/](run/), with a
`.sh` extension. There is nothing to remember beyond the directory listing:

| Script | What it does |
|---|---|
| [run/setup.sh](run/setup.sh) | Editable install with the dev extra; `--pdf` adds a local Chromium |
| [run/build.sh](run/build.sh) | Render the CV (`-f html\|pdf\|docx`, `-o`, `-t`, …) |
| [run/validate.sh](run/validate.sh) | Parse and report, write nothing |
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
there, so `data/cv.md`, `dist/` and every other relative path mean the same thing
wherever you invoke it from — including path arguments, which are read relative to
the project root rather than your shell's directory. Absolute paths are absolute.

`pip install`ing the package still puts a `cv-generator` command on PATH; the
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
cv-generator (python:3.13)  ──ws://playwright:3000/──>  playwright run-server
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
`/tmp/cv-generator/` by [.devcontainer/tool-caches.env](.devcontainer/tool-caches.env)
so they never land in the repo at all.

If a build reports `Permission denied` on a file in `dist/`, check whether Acrobat
or Word has it open on the host — Windows locks the file and the mount reports it
as a permission error.

## Usage

```bash
run/build.sh                     # data/cv.md -> dist/cv.html
run/build.sh -f pdf              # -> dist/cv.pdf
run/build.sh -f docx             # -> dist/cv.docx
run/build.sh -o out.pdf -f pdf
run/build.sh -t classic          # theme (HTML/PDF only)
run/build.sh input/other.md      # a different source file
run/validate.sh                  # parse and report, write nothing
run/themes.sh
run/engines.sh
```

Every build overwrites its target in `dist/` without asking, so the current
result is always at the same path, and copies it to
`dist/hist/<name>-<YYYYmmdd-HHMMSS>.<ext>` so the replaced one stays
recoverable. The timestamp sits before the extension, so an archived copy still
opens in the same application as the original. `dist/` is gitignored, history
included; prune `dist/hist/` whenever you like — nothing reads it back.

## The source format

One Markdown file: YAML frontmatter for identity and contact details, Markdown
below for content.

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
| `## Projekte` | Special: filled from the Word project list, see below. |
| `###` | One entry within a section: a role, a degree, a project. |
| `*italic line*` right after a `###` | Styled as the entry's date/location line. |
| Everything else | Plain Markdown — lists (nested too), bold, italic, strikethrough, inline code, fenced code, links, blockquotes, tables, rules. |

Section names are free-form: rename, reorder or drop them and every output
format follows.

## The project list comes from Word

`## Projekte` is the one section whose content is *not* in the Markdown file. It
is imported from the project list that lives next to the CV — the single `.docx`
in the same directory whose name contains **Projektliste** (any case) — from the
section headed **Projekthistorie**, with the formatting it has there:

```
data/
  cv.md                                  ## Projekte  ->  imported
  Bergemann-Projektliste_19_08_2026.docx      "Projekthistorie", one table per project
  photo.jpg
```

That file is maintained in Word and sent to clients as it is, so Word stays its
source of truth: edit it there, rebuild, and the CV follows. Whatever stands
under `## Projekte` in the Markdown file is ignored — put a comment there.

| | |
|---|---|
| Which file | The one `.docx` in the CV's directory whose name contains `projektliste`. Word's `~$…` lock file, so an open document does not count as a second match. |
| Zero or several matches | An error naming them. Guessing would quietly publish a CV built from last year's list. |
| Which part of it | From the `Projekthistorie` heading to the next paragraph formatted like it (same weight, same size) — a hand-made Word CV has no heading *styles* to go by. |
| Kept | Bold, italic, underline, strikethrough, size, colour, hyperlinks, bullets and their nesting, table columns and widths, whether the table is ruled. |
| Not kept | Font family, page setup, paragraph spacing — those stay the CV's own, so the imported projects sit in this document rather than importing a second design. |

`run/validate.sh` prints which file was used and how many blocks came out of it,
which is the thing to check before a build goes out:

```
data/cv.md: ok - Frank Bergemann, 5 section(s)
  - Projekte (projekte) <- 25 block(s) from data/Bergemann-Projektliste_19_08_2026.docx
```

All three output formats show the same imported content: HTML and PDF render the
tables with the source's widths, `.docx` writes them as real Word tables with
Word's own bullet styles.

## How it fits together

```
                                          ┌─ render.py ─> HTML ─┬─> .html
data/cv.md ────── parser.py ─> CV model ──┤                     └─ pdf/chrome.py ─> .pdf
  frontmatter        │         (pydantic) │
  + Markdown         │                    └─ word.py ──────────────────────────────> .docx
*Projektliste*.docx ─┘
  "Projekthistorie"    docx_import.py
```

- [src/cv_generator/parser.py](src/cv_generator/parser.py) — frontmatter + Markdown → model
- [src/cv_generator/models.py](src/cv_generator/models.py) — the validated `CV` schema
- [src/cv_generator/markdown.py](src/cv_generator/markdown.py) — the one Markdown parser both backends share
- [src/cv_generator/docx_import.py](src/cv_generator/docx_import.py) — the Word project list → blocks in the model
- [src/cv_generator/render.py](src/cv_generator/render.py) — model → self-contained HTML
- [src/cv_generator/word.py](src/cv_generator/word.py) — model → `.docx` (see `WordTheme`)
- [src/cv_generator/ooxml.py](src/cv_generator/ooxml.py) — the OOXML bits python-docx has no API for
- [src/cv_generator/pdf/](src/cv_generator/pdf/) — the `PdfEngine` protocol and the Chromium engine
- [src/cv_generator/templates/](src/cv_generator/templates/) — HTML themes (`cv.html.j2` + `cv.css`)

**The photo is read by the parser, not by the backends.** `photo:` is the one
key naming another file, resolved relative to the `.md` so a CV and its portrait
travel together. The model then carries the *bytes*, which is what lets the HTML
stay self-contained and the `.docx` embed the image, with neither output stage
touching the disk. Only formats both backends understand are accepted — PNG,
JPEG and GIF, sniffed from the content rather than trusted from the extension —
so a photo cannot render in one format and silently vanish from another.

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
- The **imported project list** as real Word tables: the source's column
  proportions scaled to this page, its runs' weight, size and colour, and Word's
  own bullet styles.
- The **photo**, embedded in the document, placed by a borderless layout table
  because Word has no flexbox: identity left, portrait against the right margin.
- A4 page setup, `keep-with-next` on headings so no entry title is orphaned at a
  page break, and the document language tagged for spell-check.

Word has no stylesheet, so the visual choices of `templates/classic/cv.css` are
mirrored in `WordTheme` ([word.py](src/cv_generator/word.py)). Themes given with
`-t` apply to HTML and PDF only; to restyle `.docx`, pass a `WordTheme`:

```python
from pathlib import Path
from cv_generator import WordRenderer, WordTheme, parse_cv_file

WordRenderer(WordTheme(body_font="Georgia", accent="7A2E2E")).render(
    parse_cv_file(Path("data/cv.md")), Path("dist/cv.docx")
)
```

Not supported: images inside section Markdown (the header photo is; `![...]()`
in a section body falls back to its alt text).

## Adding a theme

Copy `src/cv_generator/templates/classic/` to a new directory next to it. A theme
is exactly two files, `cv.html.j2` and `cv.css`. Keep both branches of the
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
