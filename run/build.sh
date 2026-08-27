#!/usr/bin/env bash
# Render the CV. Everything after the script name goes to `cv-generator build`.
#
#   run/build.sh                              # data/cv.md -> dist/cv.html
#   run/build.sh -f pdf                        # -> dist/cv.pdf   (needs a browser)
#   run/build.sh -f docx                       # -> dist/cv.docx
#   run/build.sh input/other.md -o out.pdf -f pdf
#   run/build.sh -t classic                    # theme (HTML/PDF only)
#
# Each run overwrites its target in place -- the current result is always at the
# same path, so nothing downstream has to guess a name -- and then copies it to
# dist/hist/<stem>-<timestamp>.<ext>, so replaced results stay recoverable. The
# timestamp goes before the extension on purpose: the copy keeps opening in the
# same application as the original.
#
# No browser reachable? run/engines.sh says so, run/browser-up.sh fixes it.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

HIST_DIR="dist/hist"

# The CLI resolves the output path itself (-o, else dist/<source stem>.<format>),
# so its "wrote <path>" line is the one place that path is known. Reading it back
# keeps a single source of truth; recomputing the same rule here would be a
# second one, free to drift the moment the CLI's default changes.
#
# Capturing stdout rather than streaming it costs nothing: `wrote` is the only
# thing build prints there, and errors go to stderr, which still streams. A
# failing build exits here (`set -e` from _lib.sh) and archives nothing.
build_output="$(cv_generator build "$@")"
printf '%s\n' "$build_output"

target="$(printf '%s\n' "$build_output" | sed -n 's/^wrote //p' | tail -n 1)"
if [ -n "$target" ] && [ -f "$target" ]; then
  name="$(basename "$target")"
  stamp="$(date +%Y%m%d-%H%M%S)"
  case "$name" in
    *.*) copy="$HIST_DIR/${name%.*}-$stamp.${name##*.}" ;;
    *) copy="$HIST_DIR/$name-$stamp" ;;
  esac
  mkdir -p "$HIST_DIR"
  cp -p "$target" "$copy"
  echo "archived $copy"
fi
