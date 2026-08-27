#!/usr/bin/env bash
# Test suite. Arguments go to pytest.
#
#   run/test.sh
#   run/test.sh tests/test_word.py
#   run/test.sh -k photo -x
#
# Careful with a green run: the PDF tests skip themselves when no browser is
# reachable and pytest still exits 0. To exercise that path, start a browser
# (run/browser-up.sh) or use run/verify-in-docker.sh, which guarantees it.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

dev_tool pytest "$@"
