"""update_order — add, modify, or remove lines in the in-flight order.

Dispatch rules:
  line_id is None             -> ADD a new line for item_name
  line_id set, quantity == 0  -> REMOVE that line
  line_id set, other args     -> MUTATE that line (swap item, change qty, change mods)

Returns the new Order plus a human-readable message and the affected line_id.
Raises ValueError on unresolvable item / modification names so the caller can
re-prompt rather than silently drop the request.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from drive_thru.db import repository as repo
from drive_thru.order_state import LineModification, Order, OrderLine


class UpdateOrderResult(BaseModel):
    order: Order
    line_id: str | None
    message: str


def update_order(
    order: Order,
    item_name: str | None = None,
    quantity: int = 1,
    modifications: list[str] | None = None,
    line_id: str | None = None,
) -> UpdateOrderResult:
    if quantity < 0:
        raise ValueError(f"quantity must be >= 0, got {quantity}")

    if line_id is not None:
        existing = order.find_line(line_id)
        if existing is None:
            raise ValueError(f"No order line with line_id={line_id!r}")
        if quantity == 0 and item_name is None and modifications is None:
            return _remove_line(order, line_id)
        return _mutate_line(order, existing, item_name, quantity, modifications)

    if item_name is None:
        raise ValueError("item_name is required when adding a new line")
    if quantity < 1:
        raise ValueError("quantity must be >= 1 when adding a new line")
    return _add_line(order, item_name, quantity, modifications or [])


# ---------- internal helpers ----------

def _resolve_item_or_combo(name: str) -> tuple[str, dict[str, Any]]:
    """Returns ('item'|'combo', row). Raises ValueError if not found."""
    conn = repo.get_connection()
    item = repo.get_menu_item_by_name(conn, name)
    if item:
        return "item", item
    combo = repo.get_combo_by_name(conn, name)
    if combo:
        return "combo", combo
    raise ValueError(f"Menu has no item or combo named {name!r}")


def _resolve_modifications(
    mod_names: list[str], category: str | None
) -> list[LineModification]:
    if not mod_names:
        return []
    conn = repo.get_connection()
    resolved: list[LineModification] = []
    for raw in mod_names:
        mod = repo.get_modification_by_name(conn, raw)
        if mod is None:
            raise ValueError(f"Unknown modification {raw!r}")
        applies_to = mod["applies_to_category"]
        if applies_to is not None and category is not None and applies_to != category:
            raise ValueError(
                f"Modification {mod['name']!r} applies to {applies_to}, "
                f"not {category}"
            )
        resolved.append(LineModification(
            name=mod["name"], price_delta_paise=mod["price_delta_paise"]
        ))
    return resolved


def _add_line(
    order: Order, item_name: str, quantity: int, mod_names: list[str]
) -> UpdateOrderResult:
    kind, row = _resolve_item_or_combo(item_name)
    category = row.get("category") if kind == "item" else None
    mods = _resolve_modifications(mod_names, category)
    line = OrderLine(
        kind=kind,
        ref_id=row["id"],
        name=row["name"],
        unit_price_paise=row["price_paise"],
        quantity=quantity,
        modifications=mods,
    )
    new_order = order.model_copy(update={"lines": [*order.lines, line]})
    return UpdateOrderResult(
        order=new_order,
        line_id=line.line_id,
        message=f"Added {quantity} x {line.name} (line {line.line_id})",
    )


def _remove_line(order: Order, line_id: str) -> UpdateOrderResult:
    removed_name = next(l.name for l in order.lines if l.line_id == line_id)
    new_lines = [l for l in order.lines if l.line_id != line_id]
    return UpdateOrderResult(
        order=order.model_copy(update={"lines": new_lines}),
        line_id=line_id,
        message=f"Removed {removed_name} (line {line_id})",
    )


def _mutate_line(
    order: Order,
    existing: OrderLine,
    item_name: str | None,
    quantity: int,
    mod_names: list[str] | None,
) -> UpdateOrderResult:
    updated_fields: dict[str, Any] = {"quantity": quantity}
    if item_name is not None:
        kind, row = _resolve_item_or_combo(item_name)
        updated_fields.update({
            "kind": kind,
            "ref_id": row["id"],
            "name": row["name"],
            "unit_price_paise": row["price_paise"],
        })
        category = row.get("category") if kind == "item" else None
    else:
        category = None
        if existing.kind == "item":
            # Look up category for mod validation against existing item.
            conn = repo.get_connection()
            row = conn.execute(
                "SELECT category FROM menu_items WHERE id = ?", (existing.ref_id,)
            ).fetchone()
            category = row["category"] if row else None
    if mod_names is not None:
        updated_fields["modifications"] = _resolve_modifications(mod_names, category)
    new_line = existing.model_copy(update=updated_fields)
    new_lines = [new_line if l.line_id == existing.line_id else l for l in order.lines]
    return UpdateOrderResult(
        order=order.model_copy(update={"lines": new_lines}),
        line_id=existing.line_id,
        message=f"Updated line {existing.line_id}: now {quantity} x {new_line.name}",
    )
