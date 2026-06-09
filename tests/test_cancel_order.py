from drive_thru.order_state import Order
from drive_thru.tools import cancel_order, update_order


def test_cancel_empty_order_reports_zero_cleared():
    result = cancel_order(Order())
    assert result.cleared_line_count == 0
    assert "0 line" in result.message


def test_cancel_with_items_reports_count():
    o = update_order(Order(), item_name="Crispy Chicken Burger").order
    o = update_order(o, item_name="Regular Meal").order
    result = cancel_order(o, reason="customer cancelled")
    assert result.cleared_line_count == 2
    assert result.reason == "customer cancelled"
    assert "2 line" in result.message


def test_cancel_default_reason():
    result = cancel_order(Order())
    assert result.reason == "customer cancelled"
    assert "cancelled" in result.message.lower()


def test_cancel_custom_reason():
    result = cancel_order(Order(), reason="customer left without ordering")
    assert "customer left without ordering" in result.message
