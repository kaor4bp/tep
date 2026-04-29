#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TEP_HOME="${TEP_HOME:-${HOME}/.tep}"

if [[ -n "${TEP_MCP_BIN:-}" ]]; then
  exec "${TEP_MCP_BIN}" --tep-home "${TEP_HOME}"
fi

if [[ ! -d "${REPO_ROOT}/src/tep" && -d "/Users/kaor4bp/PycharmProjects/tep/src/tep" ]]; then
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
from cryptography.hazmat.primitives.asymmetric import ed25519
import tep.mcp_stdio_server
PY
}

PYTHON_BIN=""
for candidate in "${TEP_PYTHON:-}" "/tmp/tep-core-venv/bin/python" "/tmp/tep-test-venv/bin/python" "python3"; do
  if python_supports_tep "${candidate}"; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_BIN}" && -x "$(command -v uv 2>/dev/null || true)" ]]; then
  rm -rf /tmp/tep-core-venv
  python3 -m venv /tmp/tep-core-venv
  if uv pip install --offline --python /tmp/tep-core-venv/bin/python -e "${REPO_ROOT}" >/dev/null 2>&1 \
    || uv pip install --python /tmp/tep-core-venv/bin/python -e "${REPO_ROOT}" >/dev/null; then
    if python_supports_tep "/tmp/tep-core-venv/bin/python"; then
      PYTHON_BIN="/tmp/tep-core-venv/bin/python"
    fi
  fi
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  cat >&2 <<EOF
TEP MCP cannot start: no Python environment can import TEP and cryptography.
Set TEP_PYTHON to a Python with dependencies installed, or run:
  python3 -m venv /tmp/tep-core-venv
  uv pip install --python /tmp/tep-core-venv/bin/python -e ${REPO_ROOT}
EOF
  exit 1
fi

exec "${PYTHON_BIN}" -m tep.mcp_stdio_server --tep-home "${TEP_HOME}"
