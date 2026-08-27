#!/usr/bin/env bash
# Start the Chromium container the PDF path talks to, and wait until it accepts
# connections.
#
# Only needed outside the dev container: inside it compose has already started
# the service and CV_GENERATOR_BROWSER_WS points at it. On the host, this plus
# the exported variable is a full PDF setup with no browser download.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_docker

# The compose network is external so neighbouring projects can share one browser
# server, which means nothing creates it implicitly. Idempotent in effect.
docker network create common_network >/dev/null 2>&1 ||
  echo "network common_network already exists"

docker compose -f "$COMPOSE_FILE" up -d playwright

# `up -d` returns when the container is running, which is before the server is
# listening -- connect() would fail on a fast machine. The image says so itself.
echo -n "waiting for the browser server"
for _ in $(seq 1 60); do
  if docker compose -f "$COMPOSE_FILE" logs playwright 2>&1 | grep -q "Listening on"; then
    echo " ok"
    cat <<'MSG'

Point the CLI at it (unset this to go back to a local browser):

  export CV_GENERATOR_BROWSER_WS=ws://localhost:3000/     # PowerShell: $env:CV_GENERATOR_BROWSER_WS="ws://localhost:3000/"
  run/engines.sh                                          # confirms: chrome [ready]
  run/build.sh -f pdf
MSG
    exit 0
  fi
  echo -n .
  sleep 2
done

echo
echo "run: the browser server did not report 'Listening on' within 120s. Logs:" >&2
docker compose -f "$COMPOSE_FILE" logs --tail 20 playwright >&2
exit 1
