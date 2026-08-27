#!/usr/bin/env bash
# Lint with ruff. Arguments go to `ruff check`; the default target is the repo.
#
#   run/lint.sh
#   run/lint.sh --fix
#   run/lint.sh src/cv_generator/word.py

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

if [ "$#" -eq 0 ]; then
  set -- .
fi

dev_tool ruff check "$@"
