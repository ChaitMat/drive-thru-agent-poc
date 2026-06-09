import json

import pytest

from drive_thru.db import repository as repo
from drive_thru.order_state import Order
from drive_thru.tools import apply_promotion, submit_order, update_order


def test_submit_empty_order_raises():
    with pytest.raises(ValueError, match="empty order"):
        submit_order(Order())


def test_submit_persists_order_and_lines():
    o = update_order(Order(), item_name="Maharaja Combo").order
    o = update_order(o, item_name="Crispy Chicken Burger",
                     modifications=["extra cheese"]).order

    result = submit_order(o)
    assert result.line_count == 2
    assert result.subtotal_paise == 34900 + (14900 + 2900)
    assert result.discount_paise == 0
    assert result.total_paise == result.subtotal_paise
    assert result.promotion_name is None

    conn = repo.get_connection()
    stored = repo.get_order(conn, result.order_id)
    assert stored is not None
    assert stored["status"] == "submitted"
    assert stored["subtotal_paise"] == result.subtotal_paise
    assert stored["discount_paise"] == 0
    assert stored["total_paise"] == result.total_paise
    assert stored["promotion_id"] is None
    assert len(stored["lines"]) == 2

    # Combo line has combo_id set, item_id null. Burger line is the inverse.
    by_kind = {("combo" if l["combo_id"] else "item"): l for l in stored["lines"]}
    assert by_kind["combo"]["item_id"] is None
    assert by_kind["item"]["combo_id"] is None

    # Modifications round-trip through JSON.
    burger_mods = json.loads(by_kind["item"]["modifications_json"])
    assert burger_mods == [{"name": "extra cheese", "price_delta_paise": 2900}]


def test_submit_persists_applied_promotion():
    o = update_order(Order(), item_name="Family Feast").order
    o = apply_promotion(o, promotion_name="Family Feast Discount").order

    result = submit_order(o)
    assert result.subtotal_paise == 79900
    assert result.discount_paise == 10000
    assert result.total_paise == 69900
    assert result.promotion_name == "Family Feast Discount"

    conn = repo.get_connection()
    stored = repo.get_order(conn, result.order_id)
    assert stored["subtotal_paise"] == 79900
    assert stored["discount_paise"] == 10000
    assert stored["total_paise"] == 69900
    assert stored["promotion_id"] is not None
