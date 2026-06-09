from drive_thru.order_state import Order
from drive_thru.tools import apply_promotion, confirm_order, update_order


def test_empty_order_summary():
    summary = confirm_order(Order())
    assert summary["is_empty"] is True
    assert summary["total_paise"] == 0
    assert summary["subtotal_paise"] == 0
    assert summary["discount_paise"] == 0
    assert summary["applied_promotion"] is None
    assert summary["lines"] == []


def test_summary_totals_match_order():
    o = update_order(Order(), item_name="Maharaja Combo").order
    o = update_order(o, item_name="Coke (Regular)", quantity=2).order
    summary = confirm_order(o)
    assert summary["is_empty"] is False
    assert summary["subtotal_paise"] == 34900 + 2 * 6900
    assert summary["discount_paise"] == 0
    assert summary["total_paise"] == 34900 + 2 * 6900
    assert summary["total_inr"] == "487.00"
    assert summary["applied_promotion"] is None
    assert len(summary["lines"]) == 2


def test_spoken_summary_mentions_each_item_and_total():
    o = update_order(Order(), item_name="Crispy Chicken Burger",
                     modifications=["extra cheese"]).order
    spoken = confirm_order(o)["spoken_summary"]
    assert "Crispy Chicken Burger" in spoken
    assert "extra cheese" in spoken
    assert "₹178" in spoken  # 14900 + 2900 = 17800 paise; voice format drops .00


def test_summary_with_applied_promotion_shows_breakdown():
    o = update_order(Order(), item_name="Family Feast").order  # ₹799
    o = apply_promotion(o, promotion_name="Family Feast Discount").order
    summary = confirm_order(o)
    assert summary["subtotal_paise"] == 79900
    assert summary["discount_paise"] == 10000
    assert summary["total_paise"] == 69900
    assert summary["applied_promotion"]["name"] == "Family Feast Discount"
    spoken = summary["spoken_summary"]
    assert "Family Feast Discount" in spoken
    assert "₹100" in spoken  # discount amount; voice format drops .00
    assert "₹699" in spoken  # final total
