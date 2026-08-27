#!/usr/bin/env bash
# Parse a CV and report what was found, writing nothing.
#
#   run/validate.sh                # data/cv.md
#   run/validate.sh input/other.md

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cv_generator validate "$@"
