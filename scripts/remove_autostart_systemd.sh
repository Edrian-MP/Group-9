#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="smartpos.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}"; then
  sudo systemctl disable --now "${SERVICE_NAME}" || true
fi

if [[ -f "${SERVICE_PATH}" ]]; then
  sudo rm -f "${SERVICE_PATH}"
  sudo systemctl daemon-reload
  echo "Removed ${SERVICE_NAME}."
else
  echo "${SERVICE_NAME} is not installed."
fi
