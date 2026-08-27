#!/usr/bin/env bash
# Install the project for local development: an editable install with the dev
# extra, into whatever interpreter is active.
#
#   run/setup.sh          # jinja2, pydantic, ... plus ruff, mypy, pytest
#   run/setup.sh --pdf    # and a local Chromium (~150 MB), for -f pdf offline
#
# The dev container does this for you on create, and gets its browser from the
# playwright service instead -- so --pdf is for a local venv on the host.
# Activate that venv first; this script installs where `pip` points.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

with_pdf=false
for arg in "$@"; do
  case "$arg" in
    --pdf) with_pdf=true ;;
    *)
      echo "usage: run/setup.sh [--pdf]" >&2
      exit 2
      ;;
  esac
done

python="$(python_bin)"

if [ "$with_pdf" = true ]; then
  "$python" -m pip install -e ".[dev,pdf]"
  # Only meaningful with a local browser; the container path needs no download.
  "$python" -m playwright install chromium
else
  "$python" -m pip install -e ".[dev]"
fi

echo
echo "installed. Next:"
echo "  run/validate.sh      # parse data/cv.md"
echo "  run/build.sh         # -> dist/cv.html"
echo "  run/engines.sh       # is a PDF browser reachable?"
