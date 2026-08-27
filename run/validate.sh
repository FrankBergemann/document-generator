#!/usr/bin/env bash
# Assemble a CV and report what was found, writing nothing. Names the file behind
# each section, which is the thing to check before a build goes out: a recipe
# resolves globs and headlines, and neither is visible in the result.
#
#   run/validate.sh                    # data/config.json
#   run/validate.sh other/config.json
#   run/validate.sh notes/talk.md      # a single .md, no recipe

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cv_generator validate "$@"
