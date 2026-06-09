"""query_menu — search the Highway Bites menu and combos."""

from __future__ import annotations

from typing import Any, Literal

from drive_thru.db import repository as repo


Category = Literal["burger", "side", "drink", "dessert", "combo"]


def query_menu(
    category: Category | None = None,
    is_veg: bool | None = None,
    name_contains: str | None = None,
    max_price_paise: int | None = None,
) -> list[dict[str, Any]]:
    """Search the menu.

    Args:
        category: One of burger, side, drink, dessert, combo. None returns all
            categories (items + combos).
        is_veg: If True, only vegetarian items. If False, only non-vegetarian.
            None returns both.
        name_contains: Substring match on name (case-insensitive).
        max_price_paise: Cap on price in paise.

    Returns:
        A list of dicts. Each dict has:
          kind: "item" or "combo"
          id, name, price_paise, is_veg, description
          category (items only), subcategory (items only)
    """
    conn = repo.get_connection()
    results: list[dict[str, Any]] = []

    if category != "combo":
        item_category = category if category in {"burger", "side", "drink", "dessert"} else None
        for row in repo.search_menu_items(
            conn,
            category=item_category,
            is_veg=is_veg,
            name_contains=name_contains,
            max_price_paise=max_price_paise,
        ):
            results.append({
                "kind": "item",
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "subcategory": row["subcategory"],
                "is_veg": bool(row["is_veg"]),
                "price_paise": row["price_paise"],
                "description": row["description"],
            })

    if category in (None, "combo"):
        for row in repo.search_combos(
            conn,
            is_veg=is_veg,
            name_contains=name_contains,
            max_price_paise=max_price_paise,
        ):
            results.append({
                "kind": "combo",
                "id": row["id"],
                "name": row["name"],
                "is_veg": bool(row["is_veg"]),
                "price_paise": row["price_paise"],
                "description": row["description"],
            })

    return results
