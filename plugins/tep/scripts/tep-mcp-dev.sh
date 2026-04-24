#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TEP_HOME="${TEP_HOME:-${HOME}/.tep}"

if command -v tep-mcp >/dev/null 2>&1; then
  exec tep-mcp --tep-home "${TEP_HOME}"
fi

if [[ ! -d "${REPO_ROOT}/src/tep" && -d "/Users/kaor4bp/PycharmProjects/tep/src/tep" ]]; then
  REPO_ROOT="/Users/kaor4bp/PycharmProjects/tep"
fi

if [[ -x "/tmp/tep-core-venv/bin/python" ]]; then
  PYTHON_BIN="/tmp/tep-core-venv/bin/python"
else
  PYTHON_BIN="python3"
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON_BIN}" -m tep.mcp_stdio_server --tep-home "${TEP_HOME}"
