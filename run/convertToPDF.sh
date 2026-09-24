#!/usr/bin/env bash
# Convert a single existing .docx file to a PDF next to it.
#
#   run/convertToPDF.sh /full/path/to/Some File.docx
#   -> /full/path/to/Some File.pdf
#
# Not a separate converter: it builds a throwaway, one-entry recipe (format
# "docx", no begin/end, so the imported span runs start to finish) and renders
# it with the project's own build pipeline -- the same docx_import.py path an
# "xlsx"/"docx" entry in data/config.json already goes through. See CLAUDE.md's
# "Imported Word sections".
#
# The argument must be a full (absolute) path: _lib.sh cd's to the project root
# before this script's own code runs, so a relative path would be read from
# there, not from wherever it was typed. Both `/like/this` and `C:\like\this`
# (or `C:/like/this`) are accepted -- this runs under bash (WSL, Git Bash, the
# dev container), but the path may have been typed or pasted Windows-style.
#
# Needs a browser reachable, same as `run/build.sh -f pdf`: run/browser-up.sh,
# or a local Chromium via `run/setup.sh --pdf`.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

if [ "$#" -ne 1 ]; then
  echo "usage: run/convertToPDF.sh /full/path/to/file.docx" >&2
  exit 2
fi

# Backslashes -> forward slashes first, so every check and both `dirname` and
# `basename` below only ever have to deal with one separator style. A drive
# letter (`C:\...`) survives this unchanged, since it has no backslash before it.
docx="$(printf '%s' "$1" | tr '\\' '/')"

case "$docx" in
  /*) ;;
  [A-Za-z]:/*) ;;
  *)
    echo "run: convertToPDF.sh needs the full path to the .docx file, got '$1'" >&2
    exit 2
    ;;
esac

case "${docx,,}" in
  *.docx) ;;
  *)
    echo "run: not a .docx file: $docx" >&2
    exit 2
    ;;
esac

if [ ! -f "$docx" ]; then
  echo "run: no such file: $docx" >&2
  exit 2
fi

dir="$(dirname "$docx")"
stem="$(basename "$docx")"
stem="${stem%.*}"
pdf="$dir/$stem.pdf"

# A JSON-quoted copy of $docx -- built with Python rather than hand-escaping,
# since the path may contain quotes, backslashes or spaces.
docx_json="$("$(python_bin)" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$docx")"

recipe="$(mktemp -t convertToPDF-XXXXXX.json)"
trap 'rm -f "$recipe"' EXIT

cat >"$recipe" <<JSON
{
  "sections": [
    {"source": $docx_json, "format": "docx"}
  ]
}
JSON

cv_generator build "$recipe" -f pdf -o "$pdf"
