#!/usr/bin/env bash
# Type-check with mypy, strict. With no arguments it checks what `files =` in
# pyproject.toml names -- src/ and tests/ both.
#
#   run/typecheck.sh
#   run/typecheck.sh src/cv_generator/parser.py

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

dev_tool mypy "$@"
