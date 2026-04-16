#!/usr/bin/env bash
set -e

APP_DIR="/home/groupnine/SmartPOS (1)"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
MAIN_FILE="$APP_DIR/main.py"

cd "$APP_DIR"
exec "$PYTHON_BIN" "$MAIN_FILE"
