"""Initialize the Highway Bites SQLite database from schema.sql + seed_data.py.

Usage:
    python -m drive_thru.db.init_db                  # uses DB_PATH from env or data/drive_thru.db
    python -m drive_thru.db.init_db --reset          # drop existing DB first
    python -m drive_thru.db.init_db --path /tmp/x.db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from drive_thru.db.seed_data import COMBOS, MENU_ITEMS, MODIFICATIONS, PROMOTIONS

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(os.getenv("DB_PATH", "data/drive_thru.db"))


def init_db(db_path: Path, reset: bool = False) -> None:
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    for item in MENU_ITEMS:
        cur.execute(
            "INSERT INTO menu_items (name, category, subcategory, is_veg, price_paise, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item["name"], item["category"], item["subcategory"], int(item["is_veg"]),
             item["price_paise"], item["description"]),
        )

    item_id_by_name = {
        name: row_id
        for row_id, name in cur.execute("SELECT id, name FROM menu_items").fetchall()
    }
    item_is_veg_by_name = {
        item["name"]: item["is_veg"] for item in MENU_ITEMS
    }

    for combo in COMBOS:
        # Combo claiming veg must not contain any non-veg item.
        if combo["is_veg"] and any(not item_is_veg_by_name[n] for n in combo["item_names"]):
            offenders = [n for n in combo["item_names"] if not item_is_veg_by_name[n]]
            raise ValueError(
                f"Combo '{combo['name']}' is marked veg but contains non-veg items: {offenders}"
            )
        cur.execute(
            "INSERT INTO combos (name, is_veg, price_paise, description) VALUES (?, ?, ?, ?)",
            (combo["name"], int(combo["is_veg"]), combo["price_paise"], combo["description"]),
        )
        combo_id = cur.lastrowid
        for item_name in combo["item_names"]:
            if item_name not in item_id_by_name:
                raise ValueError(f"Combo '{combo['name']}' references unknown item '{item_name}'")
            cur.execute(
                "INSERT INTO combo_items (combo_id, item_id, quantity) VALUES (?, ?, 1) "
                "ON CONFLICT(combo_id, item_id) DO UPDATE SET quantity = quantity + 1",
                (combo_id, item_id_by_name[item_name]),
            )

    for mod in MODIFICATIONS:
        cur.execute(
            "INSERT INTO modifications (name, price_delta_paise, applies_to_category, description) "
            "VALUES (?, ?, ?, ?)",
            (mod["name"], mod["price_delta_paise"], mod["applies_to_category"], mod["description"]),
        )

    for promo in PROMOTIONS:
        if promo["discount_type"] == "combo_price_paise" and not promo.get("condition"):
            raise ValueError(
                f"Promotion {promo['name']!r} is combo_price_paise but has no "
                f"`condition` — combo-price promos must specify what they match"
            )
        condition_json = (
            json.dumps(promo["condition"]) if promo.get("condition") else None
        )
        cur.execute(
            "INSERT INTO promotions "
            "(name, description, discount_type, discount_value, "
            " min_subtotal_paise, condition_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                promo["name"], promo["description"],
                promo["discount_type"], promo["discount_value"],
                promo.get("min_subtotal_paise"),
                condition_json,
            ),
        )


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("menu_items", "combos", "combo_items", "modifications", "promotions")
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the drive-thru SQLite DB")
    parser.add_argument("--path", type=Path, default=DEFAULT_DB_PATH, help="DB file path")
    parser.add_argument("--reset", action="store_true", help="Delete existing DB first")
    args = parser.parse_args()

    init_db(args.path, reset=args.reset)
    counts = _counts(args.path)
    print(f"Initialized {args.path}")
    for table, n in counts.items():
        print(f"  {table:15s} {n}")


if __name__ == "__main__":
    main()
