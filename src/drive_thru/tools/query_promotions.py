"""query_promotions — return all currently active promotions."""

from __future__ import annotations

from typing import Any

from drive_thru.db import repository as repo


def query_promotions() -> list[dict[str, Any]]:
    """List every active promotion with its discount structure.

    Returns dicts with: id, name, description, discount_type, discount_value.
    discount_type is one of: 'percent', 'flat_paise', 'combo_price_paise'.
    """
    conn = repo.get_connection()
    return repo.list_active_promotions(conn)
