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

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" || -z "${SUPABASE_TABLE:-}" ]]; then
  echo "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_TABLE is missing in .env.supabase"
  exit 1
fi

echo "Latest rows from ${SUPABASE_TABLE}:"
curl -m 20 -sS "${SUPABASE_URL}/rest/v1/${SUPABASE_TABLE}?select=id,queue_id,entity_type,created_at&order=id.desc&limit=20" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}"
echo
