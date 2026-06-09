import pytest

from drive_thru.order_state import Order
from drive_thru.tools import apply_promotion, update_order


def _order_for_promo_total(target_subtotal_paise: int) -> Order:
    """Build an order whose subtotal is at least target_subtotal_paise."""
    o = Order()
    # Chicken Maharaja Burger ₹269 + Maharaja Combo ₹349 = ₹618 (plenty for Student Special)
    o = update_order(o, item_name="Chicken Maharaja Burger").order
    if o.subtotal_paise < target_subtotal_paise:
        o = update_order(o, item_name="Maharaja Combo").order
    assert o.subtotal_paise >= target_subtotal_paise
    return o


# ---------- happy path ----------

def test_apply_percent_discount_above_threshold():
    """Student Special is 15% off when subtotal ≥ ₹300."""
    o = _order_for_promo_total(30000)
    subtotal_before = o.subtotal_paise

    result = apply_promotion(o, promotion_name="Student Special")

    assert result.subtotal_paise == subtotal_before
    assert result.discount_paise == subtotal_before * 15 // 100
    assert result.total_paise == subtotal_before - result.discount_paise
    assert result.order.applied_promotion is not None
    assert result.order.applied_promotion.name == "Student Special"


def test_apply_flat_discount():
    """Family Feast Discount is ₹100 flat off."""
    o = update_order(Order(), item_name="Family Feast").order  # ₹799
    result = apply_promotion(o, promotion_name="Family Feast Discount")
    assert result.subtotal_paise == 79900
    assert result.discount_paise == 10000
    assert result.total_paise == 69900


def test_order_subtotal_reflects_no_discount_until_applied():
    o = _order_for_promo_total(30000)
    assert o.discount_paise == 0
    assert o.total_paise == o.subtotal_paise


def test_order_total_drops_after_apply():
    o = _order_for_promo_total(30000)
    after = apply_promotion(o, promotion_name="Student Special").order
    assert after.total_paise < after.subtotal_paise


# ---------- validation ----------

def test_apply_below_min_subtotal_raises_with_gap():
    o = update_order(Order(), item_name="Aloo Tikki Burger").order  # ₹89
    with pytest.raises(ValueError, match="requires a subtotal of at least"):
        apply_promotion(o, promotion_name="Student Special")


def test_apply_unknown_promotion_raises():
    o = update_order(Order(), item_name="Maharaja Combo").order
    with pytest.raises(ValueError, match="No promotion named"):
        apply_promotion(o, promotion_name="Random Half-Off")


# ---------- combo_price_paise: any_n_in_category ----------

def test_two_burger_tuesday_applies_with_two_veg_burgers():
    """Two veg burgers in the order → bundled to ₹199; discount = sum − bundle."""
    o = update_order(Order(), item_name="Aloo Tikki Burger").order        # ₹89
    o = update_order(o, item_name="Veggie Supreme Burger").order          # ₹179

    result = apply_promotion(o, promotion_name="Two-Burger Tuesday")

    # 89 + 179 = 268; bundle = 199; discount = 69
    assert result.subtotal_paise == 26800
    assert result.discount_paise == 6900
    assert result.total_paise == 19900


def test_two_burger_tuesday_picks_two_most_expensive():
    """With 3 veg burgers, the promo applies to the two MOST EXPENSIVE — biggest customer-side discount."""
    o = update_order(Order(), item_name="Aloo Tikki Burger").order        # ₹89
    o = update_order(o, item_name="Corn & Cheese Burger").order           # ₹119
    o = update_order(o, item_name="Veggie Supreme Burger").order          # ₹179

    result = apply_promotion(o, promotion_name="Two-Burger Tuesday")

    # Top 2 by unit_price: 179 + 119 = 298; discount = 298 - 199 = 99
    assert result.subtotal_paise == 8900 + 11900 + 17900
    assert result.discount_paise == 9900


def test_two_burger_tuesday_skips_non_veg_burgers():
    """A chicken burger doesn't qualify; need 2 *veg* burgers."""
    o = update_order(Order(), item_name="Aloo Tikki Burger").order
    o = update_order(o, item_name="Crispy Chicken Burger").order
    with pytest.raises(ValueError, match="at least 2 veg burger"):
        apply_promotion(o, promotion_name="Two-Burger Tuesday")


def test_two_burger_tuesday_with_one_burger_raises():
    o = update_order(Order(), item_name="Aloo Tikki Burger").order
    with pytest.raises(ValueError, match="at least 2"):
        apply_promotion(o, promotion_name="Two-Burger Tuesday")


def test_two_burger_tuesday_counts_quantity_as_multiple_instances():
    """One line with qty=2 should count as 2 candidates."""
    o = update_order(Order(), item_name="Veggie Supreme Burger", quantity=2).order  # ₹179 × 2
    result = apply_promotion(o, promotion_name="Two-Burger Tuesday")
    # 179 + 179 = 358; discount = 358 - 199 = 159
    assert result.discount_paise == 15900


def test_two_burger_tuesday_refuses_when_bundle_is_not_cheaper():
    """Two of the cheapest veg burger (Aloo Tikki @ ₹89) total ₹178 — less than bundle ₹199."""
    o = update_order(Order(), item_name="Aloo Tikki Burger", quantity=2).order
    with pytest.raises(ValueError, match="no discount to apply"):
        apply_promotion(o, promotion_name="Two-Burger Tuesday")


# ---------- combo_price_paise: specific_items ----------

def test_trucker_tea_combo_applies_with_both_items():
    """Masala Chai (₹49) + Garlic Bread 2pc (₹89) → bundled ₹99; discount ₹39."""
    o = update_order(Order(), item_name="Masala Chai").order
    o = update_order(o, item_name="Garlic Bread (2 pc)").order

    result = apply_promotion(o, promotion_name="Trucker Tea Combo")
    assert result.subtotal_paise == 4900 + 8900
    assert result.discount_paise == 13800 - 9900
    assert result.total_paise == 9900


def test_trucker_tea_combo_lists_missing_items():
    o = update_order(Order(), item_name="Masala Chai").order
    with pytest.raises(ValueError, match="Garlic Bread"):
        apply_promotion(o, promotion_name="Trucker Tea Combo")


def test_maharaja_monday_applies_to_combo_line():
    """Maharaja Monday wants the Maharaja Combo specifically."""
    o = update_order(Order(), item_name="Maharaja Combo").order  # ₹349
    result = apply_promotion(o, promotion_name="Maharaja Monday")
    # 349 - 299 = 50 discount
    assert result.discount_paise == 5000
    assert result.total_paise == 29900


def test_maharaja_monday_without_maharaja_combo_raises():
    o = update_order(Order(), item_name="Crispy Chicken Combo").order
    with pytest.raises(ValueError, match="Maharaja Combo"):
        apply_promotion(o, promotion_name="Maharaja Monday")


# ---------- combo_price snapshot stays stable on later property reads ----------

def test_combo_price_discount_is_snapshotted_on_applied_promotion():
    o = update_order(Order(), item_name="Aloo Tikki Burger").order
    o = update_order(o, item_name="Veggie Supreme Burger").order
    result = apply_promotion(o, promotion_name="Two-Burger Tuesday")
    promo = result.order.applied_promotion
    assert promo is not None
    assert promo.discount_type == "combo_price_paise"
    assert promo.snapshot_discount_paise == 6900


def test_apply_to_empty_order_raises():
    with pytest.raises(ValueError, match="empty order"):
        apply_promotion(Order(), promotion_name="Student Special")


# ---------- replacement ----------

def test_applying_second_promotion_replaces_first():
    o = update_order(Order(), item_name="Family Feast").order  # ₹799
    after_first = apply_promotion(o, promotion_name="Family Feast Discount").order
    assert after_first.applied_promotion.name == "Family Feast Discount"
    assert after_first.discount_paise == 10000

    after_second = apply_promotion(after_first, promotion_name="Student Special").order
    assert after_second.applied_promotion.name == "Student Special"
    # 15% of 79900 = 11985
    assert after_second.discount_paise == 11985
