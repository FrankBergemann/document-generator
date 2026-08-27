#!/usr/bin/env bash
# The run that actually exercises the PDF path: a throwaway plain-Python
# container with no browser in it, rendering through the playwright container
# over the network. This is what a green "pytest" cannot promise you.
#
#   run/verify-in-docker.sh                 # the whole suite
#   run/verify-in-docker.sh tests/test_pdf.py -q
#
# Two details that are not optional:
#
#   * --env-file tool-caches.env. This container runs as root, and a cache it
#     writes into the bind-mounted workspace is root-owned 0755 -- which the
#     `vscode` user then cannot write, and Windows cannot repair. The env file
#     sends every cache to /tmp instead.
#   * playwright==$PLAYWRIGHT_VERSION, read from .devcontainer/.env, the same
#     source as the image tag. A mismatched client fails in connect().

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_docker

version="$(playwright_version)"
if [ -z "$version" ]; then
  echo "run: no PLAYWRIGHT_VERSION in $ENV_FILE" >&2
  exit 1
fi

"$RUN_DIR/browser-up.sh" >/dev/null

pytest_args="${*:-}"
echo "verifying against ws://playwright:3000/ with playwright==$version"

# MSYS_NO_PATHCONV keeps Git Bash on Windows from rewriting the container-side
# paths of -v and -w into Windows paths.
MSYS_NO_PATHCONV=1 docker run --rm \
  --network common_network \
  -v "$REPO_ROOT:/w" -w /w \
  --env-file "$CACHES_ENV_FILE" \
  -e CV_GENERATOR_BROWSER_WS=ws://playwright:3000/ \
  python:3.13-slim bash -c \
  "pip install -q -e '.[dev]' playwright==$version && document-generator engines | grep 'chrome \[ready\]' && pytest $pytest_args"
