#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f "${ROOT_DIR}/.env.supabase" ]]; then
  echo "Missing .env.supabase in project root."
  exit 1
fi

# shellcheck disable=SC1091
source "${ROOT_DIR}/.env.supabase"

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  echo "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is missing in .env.supabase"
  exit 1
fi

query() {
  local path="$1"
  curl -m 20 -sS "${SUPABASE_URL}/rest/v1/${path}" \
    -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}"
  echo
}

echo "=== Top Products by Volume ==="
query "owner_top_products_by_volume?select=product_name,total_kg_sold,transactions,revenue_php&limit=10"

echo "=== Top Products by Frequency ==="
query "owner_top_products_by_transactions?select=product_name,transactions,line_items,total_kg_sold,revenue_php&limit=10"

echo "=== Daily Sales Summary ==="
query "owner_daily_summary?select=sale_date,transaction_count,total_revenue_php,total_kg_sold&limit=30"
