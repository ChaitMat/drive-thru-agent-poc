import pytest

from drive_thru.order_state import Order
from drive_thru.tools import swap_meal_item, update_order


def _order_with_burger_and_regular_meal() -> tuple[Order, str, str]:
    o = Order()
    burger = update_order(o, item_name="Crispy Chicken Burger")
    meal = update_order(burger.order, item_name="Regular Meal")
    return meal.order, burger.line_id, meal.line_id


def test_upgrade_coke_only_charges_a_la_carte():
    order, burger_id, meal_id = _order_with_burger_and_regular_meal()
    result = swap_meal_item(order, meal_line_id=meal_id, new_item_name="Coke (Large)")

    # 3 lines: original burger + decomposed regular fries + upgraded large coke.
    assert len(result.order.lines) == 3
    names = {l.name for l in result.order.lines}
    assert names == {"Crispy Chicken Burger", "Regular Fries", "Coke (Large)"}

    # Pricing must be á la carte, not bundled.
    # Crispy Chicken Burger ₹149 + Regular Fries ₹79 + Coke (Large) ₹99 = ₹327
    assert result.order.total_paise == 14900 + 7900 + 9900

    # Meal line is gone, two new lines added.
    line_ids = {l.line_id for l in result.order.lines}
    assert meal_id not in line_ids
    assert burger_id in line_ids
    assert set(result.added_line_ids).issubset(line_ids)
    assert len(result.added_line_ids) == 2


def test_upgrade_fries_only_charges_a_la_carte():
    order, _, meal_id = _order_with_burger_and_regular_meal()
    result = swap_meal_item(order, meal_line_id=meal_id, new_item_name="Large Fries")

    names = {l.name for l in result.order.lines}
    assert names == {"Crispy Chicken Burger", "Large Fries", "Coke (Regular)"}
    # Crispy Chicken Burger ₹149 + Large Fries ₹119 + Coke (Regular) ₹69 = ₹337
    assert result.order.total_paise == 14900 + 11900 + 6900


def test_swap_drink_for_different_drink_works():
    """Swapping Coke (Regular) for Sprite (Large) still matches by 'drink' category."""
    order, _, meal_id = _order_with_burger_and_regular_meal()
    result = swap_meal_item(order, meal_line_id=meal_id, new_item_name="Sprite (Large)")

    names = {l.name for l in result.order.lines}
    assert names == {"Crispy Chicken Burger", "Regular Fries", "Sprite (Large)"}


def test_swap_preserves_other_order_lines():
    """Lines unrelated to the meal should be untouched."""
    o = Order()
    burger = update_order(o, item_name="Crispy Chicken Burger")
    extra_burger = update_order(burger.order, item_name="Aloo Tikki Burger")
    meal = update_order(extra_burger.order, item_name="Regular Meal")

    result = swap_meal_item(meal.order, meal_line_id=meal.line_id,
                            new_item_name="Coke (Large)")
    names = [l.name for l in result.order.lines]
    # Burgers stay in original order; meal slot becomes two lines.
    assert names[0] == "Crispy Chicken Burger"
    assert names[1] == "Aloo Tikki Burger"
    assert set(names[2:]) == {"Regular Fries", "Coke (Large)"}


def test_swap_on_non_combo_line_raises():
    o = update_order(Order(), item_name="Crispy Chicken Burger")
    with pytest.raises(ValueError, match="not a combo"):
        swap_meal_item(o.order, meal_line_id=o.line_id, new_item_name="Coke (Large)")


def test_swap_with_unknown_item_raises():
    order, _, meal_id = _order_with_burger_and_regular_meal()
    with pytest.raises(ValueError, match="no item named"):
        swap_meal_item(order, meal_line_id=meal_id, new_item_name="Truffle Soda")


def test_swap_with_burger_raises_no_matching_category():
    """A Regular Meal has no burger component, so swapping in a burger is invalid."""
    order, _, meal_id = _order_with_burger_and_regular_meal()
    with pytest.raises(ValueError, match="no .* component to swap"):
        swap_meal_item(order, meal_line_id=meal_id, new_item_name="Aloo Tikki Burger")


def test_swap_on_unknown_line_id_raises():
    order, _, _ = _order_with_burger_and_regular_meal()
    with pytest.raises(ValueError, match="No order line"):
        swap_meal_item(order, meal_line_id="Lnope", new_item_name="Coke (Large)")


def test_swap_carries_drink_mod_to_swapped_drink():
    """A 'no ice' mod on the meal must ride along onto the upgraded drink line."""
    o = Order()
    o = update_order(o, item_name="Crispy Chicken Burger").order
    meal = update_order(o, item_name="Regular Meal", modifications=["no ice"])

    result = swap_meal_item(meal.order, meal_line_id=meal.line_id, new_item_name="Coke (Large)")

    coke = next(l for l in result.order.lines if l.name == "Coke (Large)")
    fries = next(l for l in result.order.lines if l.name == "Regular Fries")
    assert [m.name for m in coke.modifications] == ["no ice"]
    assert fries.modifications == []


def test_swap_carries_side_mod_to_untouched_side_when_drink_is_swapped():
    """A 'no salt' mod stays on the fries even when only the coke is swapped."""
    o = Order()
    o = update_order(o, item_name="Crispy Chicken Burger").order
    meal = update_order(o, item_name="Regular Meal", modifications=["no salt"])

    result = swap_meal_item(meal.order, meal_line_id=meal.line_id, new_item_name="Coke (Large)")

    fries = next(l for l in result.order.lines if l.name == "Regular Fries")
    coke = next(l for l in result.order.lines if l.name == "Coke (Large)")
    assert [m.name for m in fries.modifications] == ["no salt"]
    assert coke.modifications == []


def test_swap_routes_multiple_meal_mods_to_correct_components():
    """no ice (drink) → coke; no salt (side) → fries. Independent routing."""
    o = Order()
    o = update_order(o, item_name="Crispy Chicken Burger").order
    meal = update_order(o, item_name="Regular Meal", modifications=["no ice", "no salt"])

    result = swap_meal_item(meal.order, meal_line_id=meal.line_id, new_item_name="Coke (Large)")

    fries = next(l for l in result.order.lines if l.name == "Regular Fries")
    coke = next(l for l in result.order.lines if l.name == "Coke (Large)")
    assert [m.name for m in fries.modifications] == ["no salt"]
    assert [m.name for m in coke.modifications] == ["no ice"]


def test_swap_carries_takeaway_to_every_decomposed_line():
    """A None-category mod (takeaway) attaches to every component."""
    o = Order()
    o = update_order(o, item_name="Crispy Chicken Burger").order
    meal = update_order(o, item_name="Regular Meal", modifications=["takeaway"])

    result = swap_meal_item(meal.order, meal_line_id=meal.line_id, new_item_name="Coke (Large)")

    fries = next(l for l in result.order.lines if l.name == "Regular Fries")
    coke = next(l for l in result.order.lines if l.name == "Coke (Large)")
    assert "takeaway" in [m.name for m in fries.modifications]
    assert "takeaway" in [m.name for m in coke.modifications]
