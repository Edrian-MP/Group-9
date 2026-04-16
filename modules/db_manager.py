import sqlite3
import datetime
import os
import logging
import json
from config import DB_PATH

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.check_schema_updates()
        self.seed_data() 

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                price REAL,
                stock REAL,
                image_path TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                transaction_id TEXT,
                product_name TEXT,
                weight REAL,
                total_price REAL,
                payment_method TEXT DEFAULT 'Cash',
                seller_pin TEXT DEFAULT '',
                seller_name TEXT DEFAULT 'Unknown',
                seller_role TEXT DEFAULT 'Unknown'
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                pin TEXT PRIMARY KEY,
                role TEXT,
                name TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                synced_at TEXT
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_timestamp ON sales(timestamp)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_transaction_id ON sales(transaction_id)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_product_name ON sales(product_name)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status)")
        self.conn.commit()

    def check_schema_updates(self):
        self._ensure_sales_column("payment_method", "TEXT DEFAULT 'Cash'")
        self._ensure_sales_column("seller_pin", "TEXT DEFAULT ''")
        self._ensure_sales_column("seller_name", "TEXT DEFAULT 'Unknown'")
        self._ensure_sales_column("seller_role", "TEXT DEFAULT 'Unknown'")

    def _ensure_sales_column(self, column_name, column_sql):
        try:
            self.cursor.execute(f"SELECT {column_name} FROM sales LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Updating schema: Adding %s column...", column_name)
            self.cursor.execute(f"ALTER TABLE sales ADD COLUMN {column_name} {column_sql}")
            self.conn.commit()

    def seed_data(self):
        self.seed_users()
        self.cursor.execute("SELECT count(*) FROM products")
        if self.cursor.fetchone()[0] == 0:
            default_items = [
                ("Apple", 150.00, 100.0),
                ("Banana", 80.00, 50.0),
                ("Orange", 120.00, 100.0),
                ("Mango", 200.00, 50.0)
            ]
            self.cursor.executemany("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", default_items)
            self.conn.commit()

    def seed_users(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        user_count_before_seed = self.cursor.fetchone()[0]
        allow_default_seller_inserts = user_count_before_seed == 0

        self.cursor.execute("SELECT 1 FROM users WHERE role='Owner' LIMIT 1")
        owner_exists = self.cursor.fetchone() is not None
        if not owner_exists:
            self.cursor.execute("SELECT role FROM users WHERE pin='1234' LIMIT 1")
            existing_pin = self.cursor.fetchone()
            if existing_pin and existing_pin[0] != "Owner":
                logger.warning(
                    "Skipping bootstrap owner seed: PIN 1234 belongs to role '%s'.",
                    existing_pin[0]
                )
            else:
                self.cursor.execute(
                    "INSERT OR IGNORE INTO users (pin, role, name) VALUES ('1234', 'Owner', 'Admin')"
                )

        default_sellers = [
            ("0000", "Edrian Patulot"),
            ("1111", "Ace Banaag"),
            ("2222", "Aaron Villaluna")
        ]
        for pin, default_name in default_sellers:
            self.cursor.execute("SELECT role, name FROM users WHERE pin=? LIMIT 1", (pin,))
            existing = self.cursor.fetchone()

            if not existing:
                if allow_default_seller_inserts:
                    self.cursor.execute(
                        "INSERT INTO users (pin, role, name) VALUES (?, 'Seller', ?)",
                        (pin, default_name)
                    )
                continue

            role, name = existing
            clean_name = str(name).strip() if name is not None else ""
            if role != "Seller":
                logger.info(
                    "Skipping default seller seed for PIN %s because it belongs to role '%s'.",
                    pin,
                    role
                )
                continue

            if self._is_legacy_seller_name(pin, clean_name):
                self.cursor.execute(
                    "UPDATE users SET name=?, role='Seller' WHERE pin=?",
                    (default_name, pin)
                )

        self.conn.commit()

    def _is_legacy_seller_name(self, pin, name):
        clean_name = str(name).strip() if name is not None else ""
        if not clean_name:
            return True
        return pin == "0000" and clean_name.lower() == "staff"

    def add_product(self, name, price, stock):
        try:
            self.cursor.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", 
                                (name, float(price), float(stock)))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except ValueError as e:
            logger.warning("add_product invalid value: %s", e)
            return False

    def delete_product(self, name):
        self.cursor.execute("DELETE FROM products WHERE name=?", (name,))
        self.conn.commit()

    def update_product(self, name, price, stock):
        try:
            self.cursor.execute("UPDATE products SET price=?, stock=? WHERE name=?", 
                                (float(price), float(stock), name))
            self.conn.commit()
        except ValueError as e:
            logger.warning("update_product invalid value: %s", e)

    def get_all_products(self):
        self.cursor.execute("SELECT name, price, stock FROM products")
        return self.cursor.fetchall()

    def get_product_price(self, name):
        self.cursor.execute("SELECT price FROM products WHERE name=?", (name,))
        res = self.cursor.fetchone()
        return res[0] if res else 0.0

    def deduct_stock(self, name, weight):
        self.cursor.execute("UPDATE products SET stock = stock - ? WHERE name=?", (weight, name))
        self.conn.commit()

    def save_transaction(self, cart, payment_method, transaction_id, user_info=None):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_info = user_info or {}
        seller_pin = str(user_info.get('pin') or "")
        seller_name = str(user_info.get('name') or "Unknown")
        seller_role = str(user_info.get('role') or "Unknown")
        normalized_items = []
        for item in cart:
            item_name = str(item.get('name') or "")
            item_weight = float(item.get('weight') or 0.0)
            item_total = float(item.get('total') or 0.0)
            self.cursor.execute("""
                INSERT INTO sales (
                    timestamp, transaction_id, product_name, weight, total_price,
                    payment_method, seller_pin, seller_name, seller_role
                ) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, transaction_id, item_name, item_weight, item_total,
                    payment_method, seller_pin, seller_name, seller_role
                ))
            normalized_items.append({
                "product_name": item_name,
                "weight": round(item_weight, 4),
                "total_price": round(item_total, 2)
            })

        try:
            sync_payload = {
                "timestamp": ts,
                "transaction_id": str(transaction_id or ""),
                "payment_method": str(payment_method or "Cash"),
                "seller": {
                    "pin": seller_pin,
                    "name": seller_name,
                    "role": seller_role
                },
                "items": normalized_items
            }
            self.enqueue_sync_record("sales_transaction", sync_payload, commit=False)
        except Exception as e:
            logger.warning("save_transaction sync queue enqueue failed: %s", e)

        self.conn.commit()

    def enqueue_sync_record(self, entity_type, payload, commit=True):
        payload_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            """
            INSERT INTO sync_queue (entity_type, payload_json, status, retry_count, created_at)
            VALUES (?, ?, 'pending', 0, ?)
            """,
            (str(entity_type or "generic"), payload_json, created_at)
        )
        if commit:
            self.conn.commit()

    def get_sync_queue_status(self):
        self.cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status='synced' THEN 1 ELSE 0 END) AS synced_count,
                MAX(synced_at) AS last_synced_at
            FROM sync_queue
            """
        )
        row = self.cursor.fetchone() or (0, 0, 0, None)
        return {
            "pending_count": int(row[0] or 0),
            "failed_count": int(row[1] or 0),
            "synced_count": int(row[2] or 0),
            "last_synced_at": row[3]
        }

    def backfill_sales_to_sync_queue(self, limit=None):
        """
        Enqueue historical sales transactions that were not yet inserted into sync_queue.
        Returns number of transactions queued for sync.
        """
        synced_tx_ids = set()
        try:
            self.cursor.execute(
                """
                SELECT DISTINCT json_extract(payload_json, '$.transaction_id')
                FROM sync_queue
                WHERE entity_type='sales_transaction'
                  AND json_extract(payload_json, '$.transaction_id') IS NOT NULL
                  AND TRIM(json_extract(payload_json, '$.transaction_id')) <> ''
                """
            )
            synced_tx_ids = {
                str(row[0]).strip()
                for row in (self.cursor.fetchall() or [])
                if row and row[0] is not None and str(row[0]).strip()
            }
        except sqlite3.Error as e:
            logger.warning("backfill read existing sync tx IDs failed: %s", e)

        query = """
            SELECT
                transaction_id,
                MIN(timestamp) AS ts,
                MAX(payment_method) AS payment_method,
                COALESCE(NULLIF(MAX(seller_pin), ''), '') AS seller_pin,
                COALESCE(NULLIF(MAX(seller_name), ''), 'Unknown') AS seller_name,
                COALESCE(NULLIF(MAX(seller_role), ''), 'Unknown') AS seller_role
            FROM sales
            WHERE TRIM(COALESCE(transaction_id, '')) <> ''
            GROUP BY transaction_id
            ORDER BY MIN(timestamp) ASC
        """
        if limit is not None:
            query += f" LIMIT {max(1, int(limit))}"

        self.cursor.execute(query)
        tx_rows = self.cursor.fetchall() or []
        queued_count = 0

        for tx_row in tx_rows:
            tx_id = str(tx_row[0] or "").strip()
            if not tx_id or tx_id in synced_tx_ids:
                continue

            self.cursor.execute(
                """
                SELECT product_name, weight, total_price
                FROM sales
                WHERE transaction_id=?
                ORDER BY id ASC
                """,
                (tx_id,)
            )
            item_rows = self.cursor.fetchall() or []
            if not item_rows:
                continue

            items = []
            for product_name, weight, total_price in item_rows:
                items.append({
                    "product_name": str(product_name or ""),
                    "weight": round(float(weight or 0.0), 4),
                    "total_price": round(float(total_price or 0.0), 2),
                })

            payload = {
                "timestamp": str(tx_row[1] or ""),
                "transaction_id": tx_id,
                "payment_method": str(tx_row[2] or "Cash"),
                "seller": {
                    "pin": str(tx_row[3] or ""),
                    "name": str(tx_row[4] or "Unknown"),
                    "role": str(tx_row[5] or "Unknown"),
                },
                "items": items,
            }
            self.enqueue_sync_record("sales_transaction", payload, commit=False)
            queued_count += 1

        if queued_count > 0:
            self.conn.commit()
        return queued_count

    def get_fastest_moving_items(self):
        self.cursor.execute("""
            SELECT product_name, SUM(weight) as total_vol, COUNT(*) as freq 
            FROM sales 
            GROUP BY product_name 
            ORDER BY total_vol DESC LIMIT 5
        """)
        return self.cursor.fetchall()

    def get_daily_sales_summary(self):
        self.cursor.execute("""
            SELECT date(timestamp) as sale_date,
                   COUNT(DISTINCT transaction_id) as num_transactions,
                   ROUND(SUM(total_price), 2) as revenue
            FROM sales
            GROUP BY sale_date
            ORDER BY sale_date DESC
            LIMIT 30
        """)
        return self.cursor.fetchall()

    def get_history_grouped(self, days_filter=None):
        query = """
            SELECT
                MIN(timestamp),
                transaction_id,
                COUNT(product_name),
                ROUND(SUM(total_price), 2),
                COALESCE(NULLIF(MAX(seller_name), ''), 'Unknown') || ' (' ||
                COALESCE(NULLIF(MAX(seller_role), ''), 'Unknown') || ')' AS seller,
                MAX(payment_method)
            FROM sales
        """
        if days_filter:
            query += f" WHERE timestamp >= date('now', '-{int(days_filter)} days')"

        query += """
            GROUP BY transaction_id
            ORDER BY MIN(timestamp) DESC
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def get_transaction_details(self, transaction_id):
        self.cursor.execute("SELECT product_name, weight, total_price FROM sales WHERE transaction_id=?", (transaction_id,))
        return self.cursor.fetchall()

    def get_user_by_pin(self, pin):
        self.cursor.execute("SELECT pin, role, name FROM users WHERE pin=?", (pin,))
        res = self.cursor.fetchone()
        if not res:
            return None
        return {"pin": res[0], "role": res[1], "name": res[2]}

    def _is_valid_pin(self, pin):
        pin = str(pin).strip()
        return len(pin) == 4 and pin.isdigit()

    def _normalize_seller_name(self, name):
        return str(name).strip().lower() if name is not None else ""

    def _get_seller_name_matches(self, name):
        normalized_name = self._normalize_seller_name(name)
        if not normalized_name:
            return []

        self.cursor.execute("""
            SELECT pin, name
            FROM users
            WHERE role='Seller'
              AND LOWER(TRIM(COALESCE(name, ''))) = ?
            ORDER BY pin ASC
        """, (normalized_name,))
        rows = self.cursor.fetchall()
        return [{"pin": str(row[0]), "name": str(row[1] or "")} for row in rows]

    def get_seller_accounts(self):
        self.cursor.execute("""
            SELECT pin, name
            FROM users
            WHERE role='Seller'
            ORDER BY name COLLATE NOCASE ASC, pin ASC
        """)
        return self.cursor.fetchall()

    def upsert_seller_account(self, pin, name):
        pin = str(pin).strip()
        name = str(name).strip() if name is not None else ""

        if not self._is_valid_pin(pin):
            return False, "PIN must be a 4-digit number."
        if not name:
            return False, "Name cannot be empty."

        self.cursor.execute("SELECT role FROM users WHERE pin=?", (pin,))
        existing_pin_account = self.cursor.fetchone()
        existing_name_matches = self._get_seller_name_matches(name)
        if len(existing_name_matches) > 1:
            return False, "Duplicate seller names exist. Select a seller and use Update Seller."
        existing_name_account = existing_name_matches[0] if existing_name_matches else None

        if existing_pin_account and existing_pin_account[0] != "Seller":
            return False, "PIN belongs to a non-seller account."

        try:
            if existing_name_account and existing_name_account["pin"] != pin:
                if existing_pin_account:
                    return False, "PIN is already in use by another seller account."
                self.cursor.execute(
                    "UPDATE users SET pin=?, name=?, role='Seller' WHERE pin=? AND role='Seller'",
                    (pin, name, existing_name_account["pin"])
                )
                if self.cursor.rowcount != 1:
                    return False, "Seller account not found."
                message = "Seller account updated successfully."
            elif existing_pin_account:
                self.cursor.execute("UPDATE users SET name=?, role='Seller' WHERE pin=?", (name, pin))
                message = "Seller account updated successfully."
            else:
                self.cursor.execute("INSERT INTO users (pin, role, name) VALUES (?, 'Seller', ?)", (pin, name))
                message = "Seller account added successfully."
            self.conn.commit()
            return True, message
        except sqlite3.IntegrityError:
            return False, "PIN is already in use by another account."
        except sqlite3.Error as e:
            logger.warning("upsert_seller_account failed: %s", e)
            return False, "Failed to save seller account."

    def update_seller_account(self, current_pin, new_pin, new_name):
        current_pin = str(current_pin).strip()
        new_pin = str(new_pin).strip()
        new_name = str(new_name).strip() if new_name is not None else ""

        if not self._is_valid_pin(current_pin):
            return False, "Select a valid seller account to update."
        if not self._is_valid_pin(new_pin):
            return False, "PIN must be a 4-digit number."
        if not new_name:
            return False, "Name cannot be empty."

        self.cursor.execute("SELECT role, name FROM users WHERE pin=?", (current_pin,))
        current_account = self.cursor.fetchone()
        if not current_account:
            return False, "Seller account not found."
        if current_account[0] != "Seller":
            return False, "Only seller accounts can be updated."

        self.cursor.execute("SELECT role FROM users WHERE pin=?", (new_pin,))
        pin_conflict = self.cursor.fetchone()
        if pin_conflict and new_pin != current_pin:
            if pin_conflict[0] != "Seller":
                return False, "PIN belongs to a non-seller account."
            return False, "PIN is already in use by another seller account."

        existing_name_matches = self._get_seller_name_matches(new_name)
        if len(existing_name_matches) > 1:
            return False, "Duplicate seller names exist. Resolve duplicates before updating."
        existing_name_account = existing_name_matches[0] if existing_name_matches else None
        if existing_name_account and existing_name_account["pin"] != current_pin:
            return False, "Seller name already exists. Select that seller and use Update Seller."

        current_name = str(current_account[1]).strip() if current_account[1] is not None else ""
        if current_pin == new_pin and current_name == new_name:
            return True, "Seller account is unchanged."

        try:
            self.cursor.execute(
                "UPDATE users SET pin=?, name=?, role='Seller' WHERE pin=? AND role='Seller'",
                (new_pin, new_name, current_pin)
            )
            if self.cursor.rowcount != 1:
                return False, "Seller account not found."
            self.conn.commit()
            return True, "Seller account updated successfully."
        except sqlite3.IntegrityError:
            return False, "PIN is already in use by another account."
        except sqlite3.Error as e:
            logger.warning("update_seller_account failed: %s", e)
            return False, "Failed to update seller account."

    def delete_seller_account(self, pin):
        pin = str(pin).strip()

        if not self._is_valid_pin(pin):
            return False, "PIN must be a 4-digit number."

        self.cursor.execute("SELECT role FROM users WHERE pin=?", (pin,))
        existing = self.cursor.fetchone()
        if not existing:
            return False, "Seller account not found."
        if existing[0] != "Seller":
            return False, "Only seller accounts can be deleted."

        try:
            self.cursor.execute("DELETE FROM users WHERE pin=? AND role='Seller'", (pin,))
            if self.cursor.rowcount != 1:
                return False, "Seller account not found."
            self.conn.commit()
            return True, "Seller account deleted successfully."
        except sqlite3.Error as e:
            logger.warning("delete_seller_account failed: %s", e)
            return False, "Failed to delete seller account."

    def verify_admin_pin(self, pin):
        pin = str(pin).strip()
        self.cursor.execute("SELECT 1 FROM users WHERE pin=? AND role='Owner' LIMIT 1", (pin,))
        return self.cursor.fetchone() is not None

    def change_admin_pin(self, current_pin, new_pin, confirm_pin=None):
        current_pin = str(current_pin).strip()
        new_pin = str(new_pin).strip()
        confirm_pin = str(confirm_pin).strip() if confirm_pin is not None else None

        if not self.verify_admin_pin(current_pin):
            return False, "Current admin PIN is incorrect."
        if not self._is_valid_pin(new_pin):
            return False, "New PIN must be a 4-digit number."
        if confirm_pin is not None and new_pin != confirm_pin:
            return False, "New PIN and confirmation PIN do not match."

        self.cursor.execute("SELECT role FROM users WHERE pin=?", (new_pin,))
        conflict = self.cursor.fetchone()
        if conflict and new_pin != current_pin:
            return False, "PIN is already in use by another account."
        if new_pin == current_pin:
            return True, "Admin PIN is unchanged."

        try:
            self.cursor.execute("UPDATE users SET pin=? WHERE pin=? AND role='Owner'", (new_pin, current_pin))
            if self.cursor.rowcount != 1:
                return False, "Admin account not found."
            self.conn.commit()
            return True, "Admin PIN updated successfully."
        except sqlite3.IntegrityError:
            return False, "PIN is already in use by another account."
        except sqlite3.Error as e:
            logger.warning("change_admin_pin failed: %s", e)
            return False, "Failed to update admin PIN."

    def check_login(self, pin):
        user = self.get_user_by_pin(pin)
        return user["role"] if user else None

