#!/usr/bin/env bash
# List the HTML/PDF themes available to -t/--theme.
#
#   run/themes.sh
#   run/themes.sh --templates-dir ./my-themes

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cv_generator themes "$@"
