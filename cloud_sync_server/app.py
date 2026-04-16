import os
import json
from datetime import datetime
from typing import Any, Dict
from urllib import error, request

from fastapi import FastAPI, Header, HTTPException


app = FastAPI(title="SmartPOS Cloud Sync Receiver", version="1.0.0")

API_KEY = str(os.getenv("SMARTPOS_SERVER_API_KEY", "")).strip()
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(DATA_DIR, "received_sync.jsonl")
SUPABASE_URL = str(os.getenv("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
SUPABASE_TABLE = str(os.getenv("SUPABASE_TABLE", "smartpos_sync_events")).strip() or "smartpos_sync_events"
FAIL_ON_SUPABASE_ERROR = str(os.getenv("FAIL_ON_SUPABASE_ERROR", "1")).strip().lower() in {
    "1", "true", "yes", "on"
}


def _authorize(auth_header: str) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _append_jsonl(record: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def _supabase_is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and SUPABASE_TABLE)


def _write_supabase(record: Dict[str, Any]) -> tuple[bool, str]:
    if not _supabase_is_configured():
        return False, "Supabase not configured."

    endpoint = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    payload = {
        "received_at": record.get("received_at"),
        "queue_id": record.get("queue_id"),
        "entity_type": record.get("entity_type"),
        "sent_at": record.get("sent_at"),
        "payload": record.get("payload"),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Prefer": "return=minimal",
    }

    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=10) as response:
            code = int(getattr(response, "status", 200))
            if 200 <= code < 300:
                return True, ""
            return False, f"Unexpected Supabase status {code}"
    except error.HTTPError as http_error:
        detail = ""
        try:
            detail = http_error.read().decode("utf-8", errors="replace")
        except Exception:
            detail = http_error.reason or ""
        return False, f"Supabase HTTP {http_error.code}: {detail}"[:500]
    except error.URLError as url_error:
        return False, f"Supabase URL error: {url_error.reason}"[:500]
    except Exception as e:
        return False, f"Supabase write failed: {e}"[:500]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "smartpos-cloud-sync-receiver",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "supabase_configured": _supabase_is_configured(),
        "supabase_table": SUPABASE_TABLE,
    }


@app.post("/sync")
def receive_sync(
    body: Dict[str, Any],
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    _authorize(authorization or "")

    queue_id = body.get("queue_id")
    entity_type = str(body.get("entity_type") or "")
    payload = body.get("payload")

    if queue_id is None or not entity_type or payload is None:
        raise HTTPException(status_code=400, detail="Invalid payload structure")

    record = {
        "received_at": datetime.utcnow().isoformat() + "Z",
        "queue_id": queue_id,
        "entity_type": entity_type,
        "payload": payload,
        "sent_at": body.get("sent_at"),
    }
    _append_jsonl(record)

    supabase_ok = False
    supabase_error = ""
    if _supabase_is_configured():
        supabase_ok, supabase_error = _write_supabase(record)
        if not supabase_ok and FAIL_ON_SUPABASE_ERROR:
            raise HTTPException(status_code=502, detail=f"Supabase write failed: {supabase_error}")

    return {
        "ok": True,
        "stored": 1,
        "queue_id": queue_id,
        "supabase_configured": _supabase_is_configured(),
        "supabase_ok": supabase_ok,
        "supabase_error": supabase_error,
    }

