#!/usr/bin/env bash
# Format with ruff. Arguments go to `ruff format`; the default target is the repo.
#
#   run/format.sh            # rewrite files
#   run/format.sh --check    # report only, non-zero if anything would change
#                            # (what run/check.sh and CI use)

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

# A trailing path is still allowed: `run/format.sh --check src` passes both on.
has_path=false
for arg in "$@"; do
  case "$arg" in
    -*) ;;
    *) has_path=true ;;
  esac
done
if [ "$has_path" = false ]; then
  set -- "$@" .
fi

dev_tool ruff format "$@"
