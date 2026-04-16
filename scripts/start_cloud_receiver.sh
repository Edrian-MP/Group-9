#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtual environment not found at ${PYTHON_BIN}"
  exit 1
fi

if [[ -f "${ROOT_DIR}/.env.supabase" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env.supabase"
fi

export SMARTPOS_SERVER_API_KEY="${SMARTPOS_SERVER_API_KEY:-thesis-demo-key}"

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" -m uvicorn cloud_sync_server.app:app --host 127.0.0.1 --port 8080
