#!/usr/bin/env bash
# Everything CI checks, in CI's order, so a local run means the same thing.
# Stops at the first failure (`set -e` from _lib.sh).
#
# Same caveat as run/test.sh: without a reachable browser the PDF tests skip and
# this still passes. run/verify-in-docker.sh is the run that cannot skip them.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

echo "== lint"
"$RUN_DIR/lint.sh"
echo "== format"
"$RUN_DIR/format.sh" --check
echo "== types"
"$RUN_DIR/typecheck.sh"
echo "== tests"
"$RUN_DIR/test.sh"
