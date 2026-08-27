#!/usr/bin/env bash
# Stop the browser container.
#
# `stop playwright`, not `docker compose down`: down would take the whole compose
# project with it, including the dev container you may be typing this in. The
# stopped container is also what makes run/engines.sh useful -- it reports the
# configured server separately from a missing local install, so a browser that is
# merely stopped does not look like a broken setup.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_docker

docker compose -f "$COMPOSE_FILE" stop playwright
