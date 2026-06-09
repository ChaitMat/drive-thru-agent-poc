"""swap_meal_item — break apart a meal line and swap one component á la carte.

Used when a customer wants to change ONE part of an already-added meal
(e.g. "make the coke a large" after adding Regular Meal). The meal line is
removed and replaced with its constituent items as separate lines, with the
matching-category component swapped for the upgrade. Pricing becomes á la
carte, so the customer is NOT upcharged to the next-size bundled meal.
"""

from __future__ import annotations

from pydantic import BaseModel

from drive_thru.db import repository as repo
from drive_thru.money import format_rupees
from drive_thru.order_state import Order, OrderLine


class SwapMealItemResult(BaseModel):
    order: Order
    removed_line_id: str
    added_line_ids: list[str]
    message: str


def swap_meal_item(
    order: Order,
    meal_line_id: str,
    new_item_name: str,
) -> SwapMealItemResult:
    line = order.find_line(meal_line_id)
    if line is None:
        raise ValueError(f"No order line with line_id={meal_line_id!r}")
    if line.kind != "combo":
        raise ValueError(
            f"Line {meal_line_id!r} is a {line.kind!r}, not a combo/meal — "
            f"use update_order to modify a single item line"
        )

    conn = repo.get_connection()
    constituents = repo.get_combo_items(conn, line.ref_id)
    if not constituents:
        raise ValueError(f"Combo {line.name!r} has no constituent items")

    new_item = repo.get_menu_item_by_name(conn, new_item_name)
    if new_item is None:
        raise ValueError(
            f"Menu has no item named {new_item_name!r}. "
            f"Call query_menu to find the exact name (e.g. drinks are "
            f"'Coke (Large)', 'Sprite (Regular)' — size in parentheses)."
        )

    swap_category = new_item["category"]
    matches = [c for c in constituents if c["category"] == swap_category]
    if not matches:
        raise ValueError(
            f"Meal {line.name!r} has no {swap_category!r} component to swap "
            f"for {new_item['name']!r}"
        )
    if len(matches) > 1:
        # Ambiguous — caller must use update_order on a decomposed line instead.
        names = [m["name"] for m in matches]
        raise ValueError(
            f"Meal {line.name!r} has multiple {swap_category!r} components "
            f"({names}); swap is ambiguous"
        )
    swap_target = matches[0]

    # The meal-line's existing modifications need to ride along onto the
    # right decomposed line. Pre-resolve each one's applies_to_category so we
    # can route by category match — "no ice" (drink) goes to the drink, "no
    # salt" (side) goes to the side. A mod with applies_to_category=None
    # (e.g. "takeaway") applies to every component.
    mods_by_category: dict[str | None, list] = {}
    for mod in line.modifications:
        mod_row = repo.get_modification_by_name(conn, mod.name)
        applies_to = mod_row["applies_to_category"] if mod_row else None
        mods_by_category.setdefault(applies_to, []).append(mod)

    new_lines: list[OrderLine] = []
    for c in constituents:
        chosen = new_item if c["id"] == swap_target["id"] else c
        carried_mods = (
            mods_by_category.get(chosen["category"], [])
            + mods_by_category.get(None, [])
        )
        new_lines.append(OrderLine(
            kind="item",
            ref_id=chosen["id"],
            name=chosen["name"],
            unit_price_paise=chosen["price_paise"],
            quantity=line.quantity * c["quantity"],
            modifications=list(carried_mods),
        ))

    # Splice: replace the meal line with the new á la carte lines, preserve order.
    new_order_lines: list[OrderLine] = []
    for l in order.lines:
        if l.line_id == meal_line_id:
            new_order_lines.extend(new_lines)
        else:
            new_order_lines.append(l)
    new_order = order.model_copy(update={"lines": new_order_lines})

    return SwapMealItemResult(
        order=new_order,
        removed_line_id=meal_line_id,
        added_line_ids=[l.line_id for l in new_lines],
        message=(
            f"Broke apart {line.name}: replaced {swap_target['name']} with "
            f"{new_item['name']}; now priced à la carte "
            f"({format_rupees(new_order.total_paise)} total)"
        ),
    )
