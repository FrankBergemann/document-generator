#!/usr/bin/env bash
# Render the CV. Everything after the script name goes to `document-generator build`.
#
#   run/build.sh                               # data/cv.md -> dist/cv.{html,docx,pdf}
#   run/build.sh -f html                       # -> dist/cv.html
#   run/build.sh -f pdf                        # -> dist/cv.pdf   (needs a browser)
#   run/build.sh -f docx                       # -> dist/cv.docx
#   run/build.sh -f html -f docx               # a subset; -f is repeatable
#   run/build.sh input/other.md -o out.pdf -f pdf
#   run/build.sh -t classic                    # theme (HTML/PDF only)
#
# With no -f the CV is rendered in every format. A format that fails does not
# stop the others -- with no browser reachable you still get the .html and the
# .docx, plus the pdf's error on stderr and a non-zero exit.
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
# thing build prints there, and errors go to stderr, which still streams. There
# is one line per format, so a format-less run yields several.
#
# The exit code is kept rather than left to `set -e`: a partly failing build
# (typically pdf, with no browser) still wrote the other formats, and those are
# what the archive is for. It is re-raised at the end, so the caller and CI see
# the failure either way.
build_status=0
build_output="$(cv_generator build "$@")" || build_status=$?
[ -n "$build_output" ] && printf '%s\n' "$build_output"

stamp="$(date +%Y%m%d-%H%M%S)"
while IFS= read -r target; do
  [ -n "$target" ] && [ -f "$target" ] || continue
  name="$(basename "$target")"
  case "$name" in
    *.*) copy="$HIST_DIR/${name%.*}-$stamp.${name##*.}" ;;
    *) copy="$HIST_DIR/$name-$stamp" ;;
  esac
  mkdir -p "$HIST_DIR"
  cp -p "$target" "$copy"
  echo "archived $copy"
done < <(printf '%s\n' "$build_output" | sed -n 's/^wrote //p')

exit "$build_status"
