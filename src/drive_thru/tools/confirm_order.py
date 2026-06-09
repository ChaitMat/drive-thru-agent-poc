"""confirm_order — produce a structured summary of the in-flight order.

This is what the agent reads back to the customer ("So that's a Maharaja Combo
and two Cokes, total ₹449. Confirm?") before calling submit_order.
"""

from __future__ import annotations

from typing import Any

from drive_thru.money import format_rupees
from drive_thru.order_state import Order


def confirm_order(order: Order) -> dict[str, Any]:
    """Return a summary suitable for read-back and for the UI."""
    if not order.lines:
        return {
            "is_empty": True,
            "lines": [],
            "subtotal_paise": 0,
            "discount_paise": 0,
            "total_paise": 0,
            "total_inr": "0.00",
            "applied_promotion": None,
            "spoken_summary": "Your order is empty.",
        }

    lines_out = []
    spoken_parts = []
    for line in order.lines:
        mods = [m.name for m in line.modifications]
        lines_out.append({
            "line_id": line.line_id,
            "kind": line.kind,
            "name": line.name,
            "quantity": line.quantity,
            "modifications": mods,
            "unit_price_paise": line.unit_price_paise,
            "line_total_paise": line.line_total_paise,
        })
        mod_phrase = f" with {', '.join(mods)}" if mods else ""
        qty_phrase = f"{line.quantity} {line.name}" if line.quantity > 1 else line.name
        spoken_parts.append(f"{qty_phrase}{mod_phrase}")

    subtotal = order.subtotal_paise
    discount = order.discount_paise
    total = order.total_paise
    promo = order.applied_promotion

    if promo is None:
        spoken_summary = (
            f"That's {', '.join(spoken_parts)}, "
            f"for a total of {format_rupees(total)}. Shall I place the order?"
        )
        applied_dict = None
    else:
        spoken_summary = (
            f"That's {', '.join(spoken_parts)}. "
            f"Subtotal {format_rupees(subtotal)}, {promo.name} saves "
            f"{format_rupees(discount)}, final total {format_rupees(total)}. "
            f"Shall I place the order?"
        )
        applied_dict = {
            "promotion_id": promo.promotion_id,
            "name": promo.name,
            "description": promo.description,
            "discount_type": promo.discount_type,
            "discount_value": promo.discount_value,
        }

    return {
        "is_empty": False,
        "lines": lines_out,
        "subtotal_paise": subtotal,
        "discount_paise": discount,
        "total_paise": total,
        "total_inr": f"{total / 100:.2f}",
        "applied_promotion": applied_dict,
        "spoken_summary": spoken_summary,
    }
