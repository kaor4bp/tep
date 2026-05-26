#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SERVER_URL="${TEP_SERVER_URL:-http://127.0.0.1:8765}"

if [[ -n "${TEP_SERVER_MCP_BIN:-}" ]]; then
  exec "${TEP_SERVER_MCP_BIN}" --server "${SERVER_URL}"
fi

if [[ ! -f "${REPO_ROOT}/src/tep/server_mcp_stdio.py" && -f "/Users/kaor4bp/PycharmProjects/tep/src/tep/server_mcp_stdio.py" ]]; then
  REPO_ROOT="/Users/kaor4bp/PycharmProjects/tep"
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

python_supports_tep() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 1
  if [[ "${candidate}" == */* && ! -x "${candidate}" ]]; then
    return 1
  fi
  "${candidate}" - <<'PY' >/dev/null 2>&1
import tep.server_mcp_stdio
PY
}

PYTHON_BIN=""
for candidate in "${TEP_PYTHON:-}" "${REPO_ROOT}/.venv/bin/python" "/tmp/tep-core-venv/bin/python" "/tmp/tep-test-venv/bin/python" "python3"; do
  if python_supports_tep "${candidate}"; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
  cat >&2 <<EOF
TEP MCP proxy cannot start: no Python environment can import tep.server_mcp_stdio.
Set TEP_PYTHON to a Python with this repository on PYTHONPATH, or run from the TEP repo virtualenv.
EOF
  exit 1
fi

exec "${PYTHON_BIN}" -m tep.server_mcp_stdio --server "${SERVER_URL}"
