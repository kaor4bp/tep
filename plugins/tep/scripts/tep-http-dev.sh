#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

HOST="${TEP_HTTP_HOST:-127.0.0.1}"
PORT="${TEP_HTTP_PORT:-8765}"
TEP_HOME="${TEP_HOME:-${HOME}/.tep}"

if command -v tep-http >/dev/null 2>&1; then
  exec tep-http --host "${HOST}" --port "${PORT}" --tep-home "${TEP_HOME}"
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m tep.http_server --host "${HOST}" --port "${PORT}" --tep-home "${TEP_HOME}"
