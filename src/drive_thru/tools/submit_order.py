"""submit_order — persist the finalized order to SQLite.

POS-side dispatch (POST /kitchen, POST /cashier) is intentionally deferred
until the FastAPI mock POS server exists. For now, success = a row in `orders`
plus its child rows in `order_lines`.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from drive_thru.db import repository as repo
from drive_thru.money import format_rupees
from drive_thru.order_state import Order


class SubmitOrderResult(BaseModel):
    order_id: int
    subtotal_paise: int
    discount_paise: int
    total_paise: int
    promotion_name: str | None
    line_count: int
    message: str


def submit_order(order: Order) -> SubmitOrderResult:
    if not order.lines:
        raise ValueError("Cannot submit an empty order")

    conn = repo.get_connection()
    lines_payload: list[dict[str, Any]] = []
    for line in order.lines:
        lines_payload.append({
            "item_id":            line.ref_id if line.kind == "item" else None,
            "combo_id":           line.ref_id if line.kind == "combo" else None,
            "quantity":           line.quantity,
            "modifications_json": json.dumps([m.model_dump() for m in line.modifications]),
            "line_total_paise":   line.line_total_paise,
        })

    promo = order.applied_promotion
    order_id = repo.insert_order(
        conn,
        subtotal_paise=order.subtotal_paise,
        discount_paise=order.discount_paise,
        total_paise=order.total_paise,
        promotion_id=promo.promotion_id if promo else None,
        lines=lines_payload,
    )
    return SubmitOrderResult(
        order_id=order_id,
        subtotal_paise=order.subtotal_paise,
        discount_paise=order.discount_paise,
        total_paise=order.total_paise,
        promotion_name=promo.name if promo else None,
        line_count=len(order.lines),
        message=f"Order #{order_id} submitted, total {format_rupees(order.total_paise)}",
    )
