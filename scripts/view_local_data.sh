#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

cd "${ROOT_DIR}"

"${PYTHON_BIN}" - <<'PY'
import sqlite3
from pathlib import Path

DB_PATH = Path("data/smart_pos.db")
if not DB_PATH.exists():
    print("Local DB not found:", DB_PATH)
    raise SystemExit(1)

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

print("\\n=== Local DB: latest grouped transactions ===")
cur.execute(
    """
    SELECT
      MIN(timestamp) as ts,
      transaction_id,
      COUNT(*) as items,
      ROUND(SUM(total_price), 2) as total,
      MAX(payment_method) as method,
      MAX(seller_name) as seller
    FROM sales
    GROUP BY transaction_id
    ORDER BY MIN(timestamp) DESC
    LIMIT 10
    """
)
rows = cur.fetchall()
if not rows:
    print("No sales yet.")
else:
    for row in rows:
        print(f"{row[0]} | {row[1]} | items={row[2]} | total={row[3]} | method={row[4]} | seller={row[5]}")

print("\\n=== Local DB: sync queue status ===")
cur.execute(
    """
    SELECT status, COUNT(*)
    FROM sync_queue
    GROUP BY status
    ORDER BY status
    """
)
status_rows = cur.fetchall()
if not status_rows:
    print("No sync queue records.")
else:
    for status, count in status_rows:
        print(f"{status}: {count}")

conn.close()
PY
