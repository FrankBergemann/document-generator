"""Command line interface.

Commands::

    cv-generator build data/cv.md              # -> dist/cv.html
    cv-generator build data/cv.md -f pdf       # -> dist/cv.pdf   (headless Chromium)
    cv-generator build data/cv.md -f docx      # -> dist/cv.docx  (MS Word)
    cv-generator validate data/cv.md
    cv-generator engines
    cv-generator themes
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cv_generator import __version__
from cv_generator.errors import CVError
from cv_generator.parser import parse_cv_file
from cv_generator.pdf import (
    BROWSER_WS_ENV,
    DEFAULT_ENGINE,
    KNOWN_ENGINES,
    available_engines,
    get_engine,
    implemented_engines,
    remote_endpoint,
)
from cv_generator.render import Renderer
from cv_generator.word import WordRenderer

DEFAULT_SOURCE = Path("data/cv.md")
DEFAULT_OUTPUT_DIR = Path("dist")
FORMATS = ("html", "pdf", "docx")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv-generator",
        description="Generate a CV from a single Markdown file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="render a CV")
    build.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"CV Markdown file (default: {DEFAULT_SOURCE})",
    )
    build.add_argument(
        "-f",
        "--format",
        choices=FORMATS,
        default="html",
        help="output format (default: html)",
    )
    build.add_argument("-o", "--out", type=Path, help="output file path")
    build.add_argument(
        "-t",
        "--theme",
        help="HTML/PDF theme, overriding the file's frontmatter (ignored for docx)",
    )
    build.add_argument(
        "--templates-dir",
        type=Path,
        help="directory of custom themes, instead of the built-in ones",
    )
    build.add_argument(
        "-e",
        "--engine",
        default=DEFAULT_ENGINE,
        help=f"PDF engine to use with --format pdf (default: {DEFAULT_ENGINE})",
    )
    build.set_defaults(handler=cmd_build)

    validate = subcommands.add_parser("validate", help="parse a CV without writing output")
    validate.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    validate.set_defaults(handler=cmd_validate)

    engines = subcommands.add_parser("engines", help="show PDF engine status")
    engines.set_defaults(handler=cmd_engines)

    themes = subcommands.add_parser("themes", help="list available themes")
    themes.add_argument("--templates-dir", type=Path)
    themes.set_defaults(handler=cmd_themes)

    return parser


def cmd_build(args: argparse.Namespace) -> int:
    cv = parse_cv_file(args.source)
    output: Path = args.out or DEFAULT_OUTPUT_DIR / f"{args.source.stem}.{args.format}"

    if args.format == "docx":
        WordRenderer().render(cv, output)
    else:
        html = Renderer(args.templates_dir).render_html(cv, args.theme)
        if args.format == "html":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(html, encoding="utf-8")
        else:
            get_engine(args.engine).render(html, output)

    print(f"wrote {output}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    cv = parse_cv_file(args.source)
    print(f"{args.source}: ok - {cv.name}, {len(cv.sections)} section(s)")
    if cv.photo is not None:
        # The one referenced file, so worth confirming it was found and read.
        print(f"  photo: {cv.photo.media_type}, {len(cv.photo.data) / 1024:.0f} kB")
    for section in cv.sections:
        line = f"  - {section.title} ({section.slug})"
        if section.imported_from:
            # Which file the projects came from is the thing worth checking, so
            # `validate` is where you check it before a build goes out.
            line += f" <- {len(section.blocks)} block(s) from {section.imported_from}"
        print(line)
    return 0


def cmd_engines(args: argparse.Namespace) -> int:
    ready = available_engines()
    print(f"implemented: {', '.join(implemented_engines())}")
    print(f"installed here: {', '.join(ready) if ready else 'none'}")
    # Without this, a browser container that is merely stopped looks exactly
    # like a missing local install.
    endpoint = remote_endpoint()
    if endpoint is not None:
        print(f"browser server: {endpoint} (from {BROWSER_WS_ENV})")
    print()
    for info in KNOWN_ENGINES:
        state = "implemented" if info.name in implemented_engines() else "not implemented"
        if info.name in ready:
            state = "ready"
        print(f"  {info.name} [{state}]")
        print(f"    {info.summary}")
        print(f"    trade-off:    {info.trade_off}")
        print(f"    dependencies: {info.dependencies}")
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    renderer = Renderer(args.templates_dir)
    themes = renderer.available_themes()
    print(f"themes in {renderer.templates_dir}:")
    for theme in themes or ["(none)"]:
        print(f"  - {theme}")
    print("note: docx output does not use these themes; see WordTheme in word.py")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code: int = args.handler(args)
    except CVError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
