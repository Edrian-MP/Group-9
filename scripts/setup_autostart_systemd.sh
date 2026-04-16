#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="smartpos.service"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(eval echo "~${USER_NAME}")"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  echo "Error: Python virtual environment not found at ${APP_DIR}/.venv/bin/python"
  echo "Create it first, then run this script again."
  exit 1
fi

if [[ ! -f "${APP_DIR}/scripts/start_pos_with_local_cloud.sh" ]]; then
  echo "Error: launcher script missing: ${APP_DIR}/scripts/start_pos_with_local_cloud.sh"
  exit 1
fi

echo "Installing ${SERVICE_NAME} for user ${USER_NAME}..."

TMP_UNIT="$(mktemp)"
cat > "${TMP_UNIT}" <<EOF
[Unit]
Description=SmartPOS Kiosk App
After=graphical.target network-online.target
Wants=graphical.target network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${APP_DIR}
Environment=DISPLAY=:0
Environment=XAUTHORITY=${USER_HOME}/.Xauthority
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/env bash "${APP_DIR}/scripts/start_pos_with_local_cloud.sh"
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

sudo install -m 644 "${TMP_UNIT}" "${SERVICE_PATH}"
rm -f "${TMP_UNIT}"

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

if [[ "${1:-}" == "--start-now" ]]; then
  sudo systemctl restart "${SERVICE_NAME}"
  echo "Service started."
else
  echo "Service enabled for boot."
  echo "Run: sudo systemctl start ${SERVICE_NAME}"
fi

echo "Check status with: systemctl status ${SERVICE_NAME}"
