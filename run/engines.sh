#!/usr/bin/env bash
# Report which PDF engines exist, which are installed here, and which browser
# server (if any) the PDF path was told to use. Run this before blaming -f pdf.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cv_generator engines "$@"
