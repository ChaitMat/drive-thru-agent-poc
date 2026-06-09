"""cancel_order — terminate the conversation without submitting.

The pure function is intentionally thin: it just reports what was cleared.
The state-side effect (emptying the order, flipping session_ended) lives in
the @tool wrapper as a Command, so it stays inside the LangGraph runtime.
"""

from __future__ import annotations

from pydantic import BaseModel

from drive_thru.order_state import Order


class CancelOrderResult(BaseModel):
    cleared_line_count: int
    reason: str
    message: str


def cancel_order(
    order: Order, reason: str = "customer cancelled"
) -> CancelOrderResult:
    cleared = len(order.lines)
    return CancelOrderResult(
        cleared_line_count=cleared,
        reason=reason,
        message=f"Order cancelled ({reason}). {cleared} line(s) cleared.",
    )
