"""In-memory order representation shared by the tools.

The order lives in LangGraph state across turns; tools take an Order in and
return a new Order out (no mutation). Prices are snapshotted at the time the
line is added, so promotional price changes mid-conversation don't surprise
the customer.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


def _new_line_id() -> str:
    return f"L{uuid.uuid4().hex[:6]}"


class LineModification(BaseModel):
    name: str
    price_delta_paise: int = 0


class OrderLine(BaseModel):
    line_id: str = Field(default_factory=_new_line_id)
    kind: Literal["item", "combo"]
    ref_id: int                       # menu_items.id or combos.id
    name: str                         # snapshot
    unit_price_paise: int             # snapshot, excludes modifications
    quantity: int = 1
    modifications: list[LineModification] = Field(default_factory=list)

    @property
    def line_total_paise(self) -> int:
        per_unit = self.unit_price_paise + sum(m.price_delta_paise for m in self.modifications)
        return per_unit * self.quantity


class AppliedPromotion(BaseModel):
    """Snapshot of a promotion applied to the order.

    Snapshotted (not just a foreign key) so the order's pricing is stable
    even if the promotions table is edited mid-conversation.

    For `combo_price_paise` promos the discount is dynamic (depends on which
    items in the order qualify), so it's computed once at apply time and
    stored in `snapshot_discount_paise`. For `percent` and `flat_paise`,
    discount is recomputed from `subtotal_paise * discount_value` on every
    read and `snapshot_discount_paise` stays None.
    """
    promotion_id: int
    name: str
    description: str
    discount_type: Literal["percent", "flat_paise", "combo_price_paise"]
    discount_value: int
    snapshot_discount_paise: int | None = None


class Order(BaseModel):
    lines: list[OrderLine] = Field(default_factory=list)
    applied_promotion: AppliedPromotion | None = None

    @property
    def subtotal_paise(self) -> int:
        """Pre-discount sum of all line totals."""
        return sum(l.line_total_paise for l in self.lines)

    @property
    def discount_paise(self) -> int:
        """How much the applied promotion saves on this order (always ≥ 0)."""
        promo = self.applied_promotion
        if promo is None:
            return 0
        if promo.snapshot_discount_paise is not None:
            # combo_price_paise: snapshotted at apply time.
            return min(promo.snapshot_discount_paise, self.subtotal_paise)
        if promo.discount_type == "percent":
            # Integer-floor — never over-discount.
            return self.subtotal_paise * promo.discount_value // 100
        if promo.discount_type == "flat_paise":
            return min(promo.discount_value, self.subtotal_paise)
        return 0

    @property
    def total_paise(self) -> int:
        """Final payable amount: subtotal − discount, never negative."""
        return max(0, self.subtotal_paise - self.discount_paise)

    def find_line(self, line_id: str) -> OrderLine | None:
        return next((l for l in self.lines if l.line_id == line_id), None)
