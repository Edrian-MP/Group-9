import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from urllib import error, request


logger = logging.getLogger(__name__)


class CloudSyncWorker:
    def __init__(
        self,
        db_path,
        endpoint,
        api_key="",
        enabled=False,
        interval_seconds=10,
        timeout_seconds=8,
        batch_size=25,
        max_retries=10,
    ):
        self.db_path = db_path
        self.endpoint = str(endpoint or "").strip()
        self.api_key = str(api_key or "").strip()
        self.enabled = bool(enabled)
        self.interval_seconds = max(3, int(interval_seconds or 10))
        self.timeout_seconds = max(3, int(timeout_seconds or 8))
        self.batch_size = max(1, int(batch_size or 25))
        self.max_retries = max(1, int(max_retries or 10))

        self._stop_event = threading.Event()
        self._thread = None

        self._status_lock = threading.Lock()
        self._last_sync_at = None
        self._last_error = ""
        self._last_synced_count = 0

    def start(self):
        if not self.enabled:
            logger.info("Cloud sync is disabled. Running local-only mode.")
            return
        if not self.endpoint:
            logger.warning("Cloud sync enabled but endpoint is empty. Sync worker not started.")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Cloud sync worker started.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            logger.info("Cloud sync worker stopped.")

    def get_status(self):
        with self._status_lock:
            return {
                "enabled": self.enabled,
                "endpoint_configured": bool(self.endpoint),
                "last_sync_at": self._last_sync_at,
                "last_error": self._last_error,
                "last_synced_count": self._last_synced_count,
            }

    def sync_now(self):
        if not self.enabled:
            return False, "Cloud sync is disabled."
        if not self.endpoint:
            return False, "Cloud sync endpoint is missing."

        try:
            synced_count = self._sync_once()
            self._set_status(synced_count=synced_count, error_message="")
            return True, f"Synced {synced_count} record(s)."
        except Exception as sync_error:
            logger.warning("Cloud sync manual run error: %s", sync_error)
            self._set_status(error_message=str(sync_error))
            return False, str(sync_error)

    def _set_status(self, synced_count=None, error_message=None):
        with self._status_lock:
            if synced_count is not None:
                self._last_synced_count = int(synced_count)
                if synced_count > 0:
                    self._last_sync_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if error_message is not None:
                self._last_error = str(error_message or "")[:500]

    def _run_loop(self):
        while not self._stop_event.is_set():
            synced_count = 0
            try:
                synced_count = self._sync_once()
                self._set_status(synced_count=synced_count, error_message="")
            except Exception as sync_error:
                logger.warning("Cloud sync loop error: %s", sync_error)
                self._set_status(error_message=str(sync_error))

            # Sleep in small steps to stop quickly when app exits.
            remaining = self.interval_seconds
            while remaining > 0 and not self._stop_event.is_set():
                time.sleep(min(1.0, remaining))
                remaining -= 1.0

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    def _sync_once(self):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, entity_type, payload_json, retry_count
                FROM sync_queue
                WHERE status IN ('pending', 'failed')
                  AND retry_count < ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (self.max_retries, self.batch_size),
            )
            rows = cursor.fetchall()

            if not rows:
                return 0

            synced_count = 0
            for row in rows:
                queue_id = int(row[0])
                entity_type = str(row[1] or "generic")
                payload_json = str(row[2] or "{}")
                retry_count = int(row[3] or 0)

                try:
                    payload = json.loads(payload_json)
                except json.JSONDecodeError as decode_error:
                    self._mark_failed(conn, queue_id, retry_count, f"Invalid JSON payload: {decode_error}")
                    continue

                success, error_message = self._post_record(queue_id, entity_type, payload)
                if success:
                    self._mark_synced(conn, queue_id)
                    synced_count += 1
                else:
                    self._mark_failed(conn, queue_id, retry_count, error_message)

            conn.commit()
            return synced_count
        finally:
            conn.close()

    def _post_record(self, queue_id, entity_type, payload):
        body = {
            "queue_id": queue_id,
            "entity_type": entity_type,
            "payload": payload,
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        encoded_body = json.dumps(body, ensure_ascii=True).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SmartPOS-CloudSync/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(self.endpoint, data=encoded_body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 200))
                if 200 <= status_code < 300:
                    return True, ""
                return False, f"Unexpected status code: {status_code}"
        except error.HTTPError as http_error:
            return False, f"HTTP {http_error.code}: {http_error.reason}"
        except error.URLError as url_error:
            return False, f"URL error: {url_error.reason}"
        except Exception as unknown_error:
            return False, f"Request failed: {unknown_error}"

    def _mark_synced(self, conn, queue_id):
        synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE sync_queue
            SET status='synced', synced_at=?, last_error=NULL
            WHERE id=?
            """,
            (synced_at, queue_id),
        )

    def _mark_failed(self, conn, queue_id, retry_count, error_message):
        conn.execute(
            """
            UPDATE sync_queue
            SET status='failed', retry_count=?, last_error=?
            WHERE id=?
            """,
            (retry_count + 1, str(error_message or "")[:500], queue_id),
        )

