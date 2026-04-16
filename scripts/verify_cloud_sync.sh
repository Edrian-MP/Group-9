#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
RECEIVED_FILE="${ROOT_DIR}/cloud_sync_server/received_sync.jsonl"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtual environment not found at ${PYTHON_BIN}"
  exit 1
fi

export SMARTPOS_SERVER_API_KEY="${SMARTPOS_SERVER_API_KEY:-thesis-demo-key}"
export SMARTPOS_CLOUD_SYNC_ENABLED=1
export SMARTPOS_CLOUD_SYNC_ENDPOINT="${SMARTPOS_CLOUD_SYNC_ENDPOINT:-http://127.0.0.1:8080/sync}"
export SMARTPOS_CLOUD_SYNC_API_KEY="${SMARTPOS_CLOUD_SYNC_API_KEY:-thesis-demo-key}"

cd "${ROOT_DIR}"

if ! curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
  echo "Cloud receiver is not running on 127.0.0.1:8080."
  echo "Start it first with: ./scripts/start_cloud_receiver.sh"
  exit 1
fi

"${PYTHON_BIN}" - <<'PY'
import config
from modules.db_manager import DatabaseManager
from modules.cloud_sync import CloudSyncWorker

db = DatabaseManager()
db.enqueue_sync_record(
    "sales_transaction",
    {
        "timestamp": "2026-04-09 12:00:00",
        "transaction_id": "VERIFY-SYNC-001",
        "payment_method": "Cash",
        "seller": {"pin": "0000", "name": "Verifier", "role": "Seller"},
        "items": [{"product_name": "Apple", "weight": 1.0, "total_price": 150.0}],
    },
)

worker = CloudSyncWorker(
    db_path=config.DB_PATH,
    endpoint=config.CLOUD_SYNC_ENDPOINT,
    api_key=config.CLOUD_SYNC_API_KEY,
    enabled=True,
)
ok, message = worker.sync_now()
print(f"manual_sync_ok={ok}")
print(f"manual_sync_message={message}")
PY

if [[ ! -f "${RECEIVED_FILE}" ]]; then
  echo "No received sync file found at ${RECEIVED_FILE}"
  exit 1
fi

echo "Last synced record:"
tail -n 1 "${RECEIVED_FILE}"

echo "Cloud sync verification complete."
