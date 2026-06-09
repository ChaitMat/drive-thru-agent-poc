"""apply_promotion — attach an order-level discount to the in-flight order.

Three discount types are supported:
  - `percent`           — `discount_value` is % off the whole order; dynamic
  - `flat_paise`        — `discount_value` is paise off the whole order; dynamic
  - `combo_price_paise` — `discount_value` is the bundled price for the items
                          described by the promo's `condition`; the discount
                          is computed once at apply time and SNAPSHOTTED onto
                          AppliedPromotion (the order can change after, but
                          the customer needs to re-apply if items change so
                          much that the condition no longer holds).

Validation done here:
  - promotion exists in the DB, is marked active
  - order is non-empty
  - for percent/flat: subtotal meets `min_subtotal_paise` (if set)
  - for combo_price: the promo has a `condition`, the condition is met by the
    current order, and the bundle price is strictly less than the matching
    items' total (otherwise the "discount" would be ≤ 0)

Time-of-day and day-of-week conditions are NOT validated. The promotion
description carries those and they're the agent's responsibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from drive_thru.db import repository as repo
from drive_thru.money import format_rupees
from drive_thru.order_state import AppliedPromotion, Order


class ApplyPromotionResult(BaseModel):
    order: Order
    promotion_name: str
    subtotal_paise: int
    discount_paise: int
    total_paise: int
    message: str


def apply_promotion(order: Order, promotion_name: str) -> ApplyPromotionResult:
    if not order.lines:
        raise ValueError("Cannot apply a promotion to an empty order")

    conn = repo.get_connection()
    promo_row = repo.get_promotion_by_name(conn, promotion_name)
    if promo_row is None:
        raise ValueError(
            f"No promotion named {promotion_name!r}. Call query_promotions to "
            f"see active promotions."
        )
    if not promo_row["active"]:
        raise ValueError(f"Promotion {promo_row['name']!r} is not currently active")

    discount_type = promo_row["discount_type"]
    snapshot_discount: int | None = None

    if discount_type == "combo_price_paise":
        condition = promo_row.get("condition")
        if not condition:
            raise ValueError(
                f"Promotion {promo_row['name']!r} is combo-price but has no "
                f"condition recorded in the DB — cannot evaluate"
            )
        snapshot_discount = _evaluate_combo_price(
            order, condition, bundle_paise=promo_row["discount_value"]
        )
    else:
        min_subtotal = promo_row["min_subtotal_paise"]
        if min_subtotal is not None and order.subtotal_paise < min_subtotal:
            raise ValueError(
                f"Promotion {promo_row['name']!r} requires a subtotal of at least "
                f"{format_rupees(min_subtotal)}; current subtotal is "
                f"{format_rupees(order.subtotal_paise)}. Customer needs to add "
                f"{format_rupees(min_subtotal - order.subtotal_paise)} more to qualify."
            )

    promo = AppliedPromotion(
        promotion_id=promo_row["id"],
        name=promo_row["name"],
        description=promo_row["description"],
        discount_type=discount_type,
        discount_value=promo_row["discount_value"],
        snapshot_discount_paise=snapshot_discount,
    )
    new_order = order.model_copy(update={"applied_promotion": promo})

    return ApplyPromotionResult(
        order=new_order,
        promotion_name=promo.name,
        subtotal_paise=new_order.subtotal_paise,
        discount_paise=new_order.discount_paise,
        total_paise=new_order.total_paise,
        message=(
            f"Applied {promo.name}: saved {format_rupees(new_order.discount_paise)} "
            f"(subtotal {format_rupees(new_order.subtotal_paise)} → "
            f"total {format_rupees(new_order.total_paise)})."
        ),
    )


# ---------- combo-price evaluators ----------

def _evaluate_combo_price(order: Order, condition: dict[str, Any], bundle_paise: int) -> int:
    """Return the discount in paise for a combo-price promo, or raise.

    Discount = (sum of qualifying items' unit prices) − bundle_paise.
    Modifications stay on their own lines (uncharged by the bundle).
    """
    cond_type = condition.get("type")
    if cond_type == "specific_items":
        return _eval_specific_items(order, condition["items"], bundle_paise)
    if cond_type == "any_n_in_category":
        return _eval_any_n_in_category(
            order,
            n=condition["n"],
            category=condition["category"],
            is_veg_filter=condition.get("is_veg"),
            bundle_paise=bundle_paise,
        )
    raise ValueError(f"Unknown combo-price condition type: {cond_type!r}")


def _eval_specific_items(
    order: Order, required_names: list[str], bundle_paise: int
) -> int:
    """Every name in required_names must appear at least once on the order.

    Discount is computed against one instance of each (unit_price each). Extra
    quantities pay full price; mods are already on their own lines and stay
    untouched.
    """
    # Build a lowercase name → line map for case-insensitive matching.
    by_name = {l.name.lower(): l for l in order.lines}
    matched_total = 0
    missing: list[str] = []
    for required in required_names:
        line = by_name.get(required.lower())
        if line is None:
            missing.append(required)
        else:
            matched_total += line.unit_price_paise

    if missing:
        raise ValueError(
            f"This promotion needs all of these items on the order: "
            f"{required_names}. Missing: {missing}. Add them first."
        )

    discount = matched_total - bundle_paise
    if discount <= 0:
        raise ValueError(
            f"Bundle price {format_rupees(bundle_paise)} is not less than the "
            f"matching items' total {format_rupees(matched_total)} — there's no "
            f"discount to apply."
        )
    return discount


def _eval_any_n_in_category(
    order: Order,
    *,
    n: int,
    category: str,
    is_veg_filter: bool | None,
    bundle_paise: int,
) -> int:
    """At least N item-lines must match (category, is_veg).

    Quantities count as separate instances (qty=2 → 2 candidates). The N most
    expensive matching instances form the bundle (customer-favorable: largest
    possible discount).
    """
    conn = repo.get_connection()
    candidates: list[int] = []  # unit_prices, one entry per qualifying instance

    for line in order.lines:
        if line.kind != "item":
            continue  # combos don't count toward "burgers"; tightening this
                       # would need per-combo unpacking
        row = conn.execute(
            "SELECT category, is_veg FROM menu_items WHERE id = ?",
            (line.ref_id,),
        ).fetchone()
        if row is None or row["category"] != category:
            continue
        if is_veg_filter is not None and bool(row["is_veg"]) != bool(is_veg_filter):
            continue
        candidates.extend([line.unit_price_paise] * line.quantity)

    if len(candidates) < n:
        kind_label = (
            f"{'veg ' if is_veg_filter else 'non-veg ' if is_veg_filter is False else ''}"
            f"{category} item"
        )
        raise ValueError(
            f"This promotion needs at least {n} {kind_label}(s) on the order; "
            f"only {len(candidates)} found. Add more to qualify."
        )

    # Pick N most expensive → biggest discount for the customer.
    candidates.sort(reverse=True)
    matched_total = sum(candidates[:n])

    discount = matched_total - bundle_paise
    if discount <= 0:
        raise ValueError(
            f"Bundle price {format_rupees(bundle_paise)} is not less than the "
            f"top-{n} matching items' total {format_rupees(matched_total)} — "
            f"there's no discount to apply."
        )
    return discount
