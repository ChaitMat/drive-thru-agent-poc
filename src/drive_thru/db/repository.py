"""Read/write helpers over the Highway Bites SQLite DB.

Tools call into this module rather than touching sqlite3 directly, so that
DB path resolution, connection caching, and row-to-dict conversion live in
one place.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_PATH = Path(os.getenv("DB_PATH", "data/drive_thru.db"))

_conn_lock = threading.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a process-cached connection for the given DB path."""
    path = str(Path(db_path or DEFAULT_DB_PATH).resolve())
    with _conn_lock:
        conn = _connections.get(path)
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            _connections[path] = conn
        return conn


def close_all() -> None:
    with _conn_lock:
        for conn in _connections.values():
            conn.close()
        _connections.clear()


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


# ---------- menu items ----------

def search_menu_items(
    conn: sqlite3.Connection,
    *,
    category: str | None = None,
    is_veg: bool | None = None,
    name_contains: str | None = None,
    max_price_paise: int | None = None,
    available_only: bool = True,
) -> list[dict[str, Any]]:
    sql = ["SELECT id, name, category, subcategory, is_veg, price_paise, description, available",
           "FROM menu_items WHERE 1=1"]
    params: list[Any] = []
    if available_only:
        sql.append("AND available = 1")
    if category is not None:
        sql.append("AND category = ?"); params.append(category)
    if is_veg is not None:
        sql.append("AND is_veg = ?"); params.append(int(is_veg))
    if name_contains:
        sql.append("AND LOWER(name) LIKE ?"); params.append(f"%{name_contains.lower()}%")
    if max_price_paise is not None:
        sql.append("AND price_paise <= ?"); params.append(max_price_paise)
    sql.append("ORDER BY category, price_paise")
    return _rows(conn.execute(" ".join(sql), params))


def get_menu_item_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, category, subcategory, is_veg, price_paise, description, available "
        "FROM menu_items WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    return dict(row) if row else None


# ---------- combos ----------

def search_combos(
    conn: sqlite3.Connection,
    *,
    is_veg: bool | None = None,
    name_contains: str | None = None,
    max_price_paise: int | None = None,
    available_only: bool = True,
) -> list[dict[str, Any]]:
    sql = ["SELECT id, name, is_veg, price_paise, description, available",
           "FROM combos WHERE 1=1"]
    params: list[Any] = []
    if available_only:
        sql.append("AND available = 1")
    if is_veg is not None:
        sql.append("AND is_veg = ?"); params.append(int(is_veg))
    if name_contains:
        sql.append("AND LOWER(name) LIKE ?"); params.append(f"%{name_contains.lower()}%")
    if max_price_paise is not None:
        sql.append("AND price_paise <= ?"); params.append(max_price_paise)
    sql.append("ORDER BY price_paise")
    return _rows(conn.execute(" ".join(sql), params))


def get_combo_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, is_veg, price_paise, description, available "
        "FROM combos WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def get_combo_items(conn: sqlite3.Connection, combo_id: int) -> list[dict[str, Any]]:
    return _rows(conn.execute(
        "SELECT m.id, m.name, m.category, m.is_veg, m.price_paise, ci.quantity "
        "FROM combo_items ci JOIN menu_items m ON m.id = ci.item_id "
        "WHERE ci.combo_id = ?",
        (combo_id,),
    ))


# ---------- modifications ----------

def get_modification_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, price_delta_paise, applies_to_category, description "
        "FROM modifications WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def list_modifications(
    conn: sqlite3.Connection, *, applies_to_category: str | None = None
) -> list[dict[str, Any]]:
    if applies_to_category:
        return _rows(conn.execute(
            "SELECT id, name, price_delta_paise, applies_to_category, description "
            "FROM modifications WHERE applies_to_category IS NULL OR applies_to_category = ? "
            "ORDER BY name",
            (applies_to_category,),
        ))
    return _rows(conn.execute(
        "SELECT id, name, price_delta_paise, applies_to_category, description "
        "FROM modifications ORDER BY name"
    ))


# ---------- promotions ----------

def _attach_parsed_condition(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.pop("condition_json", None)
    row["condition"] = json.loads(raw) if raw else None
    return row


def list_active_promotions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _rows(conn.execute(
        "SELECT id, name, description, discount_type, discount_value, "
        "       min_subtotal_paise, condition_json "
        "FROM promotions WHERE active = 1 ORDER BY id"
    ))
    return [_attach_parsed_condition(r) for r in rows]


def get_promotion_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, description, discount_type, discount_value, "
        "       min_subtotal_paise, condition_json, active "
        "FROM promotions WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return _attach_parsed_condition(dict(row))


# ---------- orders (write) ----------

def insert_order(
    conn: sqlite3.Connection,
    *,
    subtotal_paise: int,
    discount_paise: int,
    total_paise: int,
    promotion_id: int | None,
    lines: Iterable[dict[str, Any]],
) -> int:
    """Persist a submitted order.

    Each line dict must have: item_id (int|None), combo_id (int|None),
    quantity (int), modifications_json (str), line_total_paise (int).
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO orders "
        "(subtotal_paise, discount_paise, total_paise, promotion_id, status) "
        "VALUES (?, ?, ?, ?, 'submitted')",
        (subtotal_paise, discount_paise, total_paise, promotion_id),
    )
    order_id = cur.lastrowid
    for line in lines:
        cur.execute(
            "INSERT INTO order_lines "
            "(order_id, item_id, combo_id, quantity, modifications_json, line_total_paise) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, line["item_id"], line["combo_id"], line["quantity"],
             line["modifications_json"], line["line_total_paise"]),
        )
    conn.commit()
    return order_id


def get_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, created_at, subtotal_paise, discount_paise, total_paise, "
        "       promotion_id, status FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if not row:
        return None
    order = dict(row)
    order["lines"] = _rows(conn.execute(
        "SELECT id, item_id, combo_id, quantity, modifications_json, line_total_paise "
        "FROM order_lines WHERE order_id = ? ORDER BY id",
        (order_id,),
    ))
    return order
