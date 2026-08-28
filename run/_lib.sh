#!/usr/bin/env bash
# Shared setup for the scripts in this directory. Sourced, never executed.
#
# Every run/*.sh starts with `source .../_lib.sh`, so all of them agree on where
# the project root is, how to reach the CLI, and what to say when a tool is
# missing. Keep the individual scripts thin enough to read in one glance; put
# anything two of them need here.

set -euo pipefail

# Resolved from this file's location rather than $PWD, so a script behaves the
# same whether it is invoked as `run/build.sh`, `./build.sh` or by absolute path.
# The `cd` is what makes the CLI's own defaults (data/document.md, dist/) mean the same
# thing from any directory; the price is that a relative path *argument* is also
# read relative to the project root, which is the documented rule.
RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RUN_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Relative on purpose: compose treats the file's directory as the project
# directory, which is how .devcontainer/.env gets read for PLAYWRIGHT_VERSION.
COMPOSE_FILE=".devcontainer/docker-compose.yml"
ENV_FILE=".devcontainer/.env"
CACHES_ENV_FILE=".devcontainer/tool-caches.env"

python_bin() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
  else
    echo python
  fi
}

# `document-generator` is on PATH after `pip install -e .`, but not in a shell older
# than the install and not when the package was only put on sys.path.
# `python -m cv_generator.cli` reaches the same main() either way.
cv_generator() {
  if command -v document-generator >/dev/null 2>&1; then
    document-generator "$@"
  else
    "$(python_bin)" -m cv_generator.cli "$@"
  fi
}

# ruff, mypy and pytest come from the dev extra. "command not found" does not
# say that, so check before running rather than after failing -- and never
# swallow the tool's own non-zero exit, which is a finding, not an error.
dev_tool() {
  local tool="$1"
  shift
  if command -v "$tool" >/dev/null 2>&1; then
    "$tool" "$@"
    return
  fi
  local python
  python="$(python_bin)"
  if "$python" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$tool') else 1)"; then
    "$python" -m "$tool" "$@"
    return
  fi
  echo "run: $tool is not installed. Install the dev extra:" >&2
  echo "  pip install -e '.[dev]'" >&2
  return 1
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "run: docker is not on PATH; this script needs it." >&2
    return 1
  fi
}

# The single source of truth for the Playwright version is the compose .env,
# because the browser image tag and the pip client must match.
playwright_version() {
  sed -n 's/^PLAYWRIGHT_VERSION=//p' "$ENV_FILE"
}
