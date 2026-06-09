import pytest

from drive_thru.order_state import Order
from drive_thru.tools import update_order


def test_add_single_item():
    result = update_order(Order(), item_name="Crispy Chicken Burger")
    assert len(result.order.lines) == 1
    line = result.order.lines[0]
    assert line.name == "Crispy Chicken Burger"
    assert line.quantity == 1
    assert line.line_total_paise == 14900
    assert result.line_id == line.line_id


def test_add_combo_resolves_to_combo_kind():
    result = update_order(Order(), item_name="Maharaja Combo")
    assert result.order.lines[0].kind == "combo"
    assert result.order.lines[0].line_total_paise == 34900


def test_add_with_modifications_adjusts_price():
    result = update_order(
        Order(),
        item_name="Crispy Chicken Burger",
        modifications=["extra cheese", "no onion"],
    )
    line = result.order.lines[0]
    mod_names = {m.name for m in line.modifications}
    assert mod_names == {"extra cheese", "no onion"}
    # 14900 base + 2900 cheese + 0 no onion
    assert line.line_total_paise == 17800


def test_add_unknown_item_raises():
    with pytest.raises(ValueError, match="no item or combo"):
        update_order(Order(), item_name="Truffle Wagyu Burger")


def test_modification_category_mismatch_raises():
    # 'no salt' applies to sides only — adding it to a burger should fail.
    with pytest.raises(ValueError, match="applies to side"):
        update_order(
            Order(),
            item_name="Crispy Chicken Burger",
            modifications=["no salt"],
        )


def test_eval_case_3_multi_item_isolated_mods():
    """Eval case 3: two items with separate modifications, no cross-contamination."""
    o = Order()
    o = update_order(o, item_name="Crispy Chicken Burger",
                     modifications=["extra cheese"]).order
    o = update_order(o, item_name="Large Fries", modifications=["no salt"]).order
    assert len(o.lines) == 2
    burger, fries = o.lines
    assert [m.name for m in burger.modifications] == ["extra cheese"]
    assert [m.name for m in fries.modifications] == ["no salt"]


def test_eval_case_4_mutate_existing_line_via_line_id():
    """Eval case 4: 'make that a large' should mutate, not duplicate."""
    o = Order()
    add = update_order(o, item_name="Regular Fries")
    swapped = update_order(
        add.order, item_name="Large Fries", line_id=add.line_id, quantity=1,
    )
    assert len(swapped.order.lines) == 1
    line = swapped.order.lines[0]
    assert line.name == "Large Fries"
    assert line.line_id == add.line_id  # same line, mutated in place
    assert line.line_total_paise == 11900


def test_quantity_zero_with_line_id_removes_line():
    o = Order()
    a = update_order(o, item_name="Coke (Regular)")
    b = update_order(a.order, item_name="Crispy Chicken Burger")
    assert len(b.order.lines) == 2
    after = update_order(b.order, line_id=a.line_id, quantity=0)
    assert len(after.order.lines) == 1
    assert after.order.lines[0].name == "Crispy Chicken Burger"


def test_quantity_multiplies_correctly():
    result = update_order(Order(), item_name="Coke (Regular)", quantity=3)
    line = result.order.lines[0]
    assert line.quantity == 3
    assert line.line_total_paise == 3 * 6900


def test_missing_item_name_when_adding_raises():
    with pytest.raises(ValueError, match="item_name is required"):
        update_order(Order())


def test_negative_quantity_rejected():
    with pytest.raises(ValueError, match="must be >= 0"):
        update_order(Order(), item_name="Coke (Regular)", quantity=-1)


def test_update_unknown_line_id_raises():
    with pytest.raises(ValueError, match="No order line"):
        update_order(Order(), line_id="LDOESNT", quantity=2)
