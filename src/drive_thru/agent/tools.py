"""LangChain @tool wrappers around the pure Python tools.

The stateless tools (`query_menu`, `query_promotions`) return plain values.
The stateful tools (`update_order`, `confirm_order`, `submit_order`) use
LangGraph's InjectedState pattern: the LLM doesn't see the Order; the runtime
splices it in. Stateful mutations are returned as Command objects so that
state and messages update atomically.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from drive_thru.order_state import Order, OrderLine
from drive_thru.tools import apply_promotion as _apply_promotion
from drive_thru.tools import cancel_order as _cancel_order
from drive_thru.tools import confirm_order as _confirm_order
from drive_thru.tools import query_menu as _query_menu
from drive_thru.tools import query_promotions as _query_promotions
from drive_thru.tools import submit_order as _submit_order
from drive_thru.tools import swap_meal_item as _swap_meal_item
from drive_thru.tools import update_order as _update_order


def _line_snapshot(line: OrderLine | None) -> dict[str, Any] | None:
    """Compact JSON snapshot of one OrderLine for tool-message payloads.

    Gives the LLM enough context to know what's currently on a line so it
    can append modifications correctly instead of replacing them blindly.
    """
    if line is None:
        return None
    return {
        "line_id": line.line_id,
        "kind": line.kind,
        "name": line.name,
        "quantity": line.quantity,
        "modifications": [m.name for m in line.modifications],
        "line_total_paise": line.line_total_paise,
    }


@tool
def query_menu(
    category: str | None = None,
    is_veg: bool | None = None,
    name_contains: str | None = None,
    max_price_paise: int | None = None,
) -> list[dict[str, Any]]:
    """Search the Highway Bites menu and combos.

    Args:
        category: One of "burger", "side", "drink", "dessert", or "combo".
            Omit to search across all categories (items + combos).
        is_veg: True for vegetarian-only, False for non-vegetarian-only,
            omit for both.
        name_contains: Case-insensitive substring match on the item name.
        max_price_paise: Cap on price in paise (₹1 = 100 paise).

    Returns:
        A list of result dicts, each with kind ("item" or "combo"), id, name,
        price_paise, is_veg, description, and (for items only) category and
        subcategory.
    """
    return _query_menu(
        category=category,
        is_veg=is_veg,
        name_contains=name_contains,
        max_price_paise=max_price_paise,
    )


@tool
def query_promotions() -> list[dict[str, Any]]:
    """List currently active promotions (deals, offers, discounts).

    Returns dicts with id, name, description, discount_type
    ('percent' | 'flat_paise' | 'combo_price_paise'), and discount_value.
    """
    return _query_promotions()


@tool
def update_order(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    item_name: str | None = None,
    quantity: int = 1,
    modifications: list[str] | None = None,
    line_id: str | None = None,
) -> Command:
    """Add, mutate, or remove a line on the customer's in-flight order.

    Dispatch:
      - ADD a new line: pass `item_name` (exact from query_menu) and optionally
        `quantity` and `modifications`. Do NOT pass `line_id`.
      - MUTATE an existing line: pass `line_id` from a prior update_order
        result, plus the fields to change (new item_name to swap, new quantity,
        new modifications).
      - REMOVE a line: pass `line_id` and quantity=0.

    Args:
        item_name: Exact item or combo name from a prior query_menu result.
        quantity: 1+ to add or set. 0 (with line_id) removes the line.
        modifications: List of exact modification names (e.g. "extra cheese",
            "no salt", "no onion"). When mutating, this REPLACES the line's
            modifications.
        line_id: ID of an existing line, from a prior update_order result.

    Returns the updated order state plus a short confirmation message.
    """
    order: Order = state.get("order") or Order()
    result = _update_order(
        order=order,
        item_name=item_name,
        quantity=quantity,
        modifications=modifications,
        line_id=line_id,
    )
    line = result.order.find_line(result.line_id) if result.line_id else None
    payload = {
        "line_id": result.line_id,
        "message": result.message,
        "order_total_paise": result.order.total_paise,
        "line_count": len(result.order.lines),
        "line": _line_snapshot(line),
    }
    return Command(update={
        "order": result.order,
        "messages": [ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)],
    })


@tool
def confirm_order(
    state: Annotated[dict, InjectedState],
) -> dict[str, Any]:
    """Return a structured read-back of the in-flight order.

    Use this before submit_order so you can read the spoken_summary back to
    the customer and let them confirm or change something.

    Returns a dict with `lines`, `total_paise`, `total_inr`, `is_empty`, and
    `spoken_summary` (a natural-language phrase ready to read aloud).
    """
    order: Order = state.get("order") or Order()
    return _confirm_order(order)


@tool
def apply_promotion(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    promotion_name: str,
) -> Command:
    """Apply a promotion (discount) to the in-flight order.

    All three discount types are supported:
      - `percent` — % off the whole order (e.g. Student Special).
      - `flat_paise` — fixed paise off the whole order (e.g. Family Feast Discount).
      - `combo_price_paise` — bundled price for a set of items the promo specifies
        (e.g. Two-Burger Tuesday: any two veg burgers for ₹199;
        Maharaja Monday: Maharaja Combo for ₹299). The tool finds the matching
        items in the order, picks the customer-favorable combination, and computes
        the discount automatically.

    Use after the customer agrees to use a promotion you've discussed with them.

    What the tool validates:
      - Promotion exists and is active.
      - Order is non-empty.
      - For percent / flat_paise: subtotal meets the promo's min_subtotal_paise.
      - For combo_price_paise: the required items are on the order and the
        bundle price is strictly less than their total (otherwise there'd be
        no discount).

    What the tool does NOT validate (your responsibility):
      - Time-of-day conditions in the description ("between 3pm and 6pm").
      - Day-of-week conditions ("Tuesdays only", "Mondays").

    On validation failure, raises ValueError with a customer-friendly explanation
    you can relay (e.g. "needs ₹X more to qualify"). Only one promotion can be
    applied at a time — calling again replaces the previously applied one.

    Args:
        promotion_name: Exact name from a `query_promotions` result.
    """
    order: Order = state.get("order") or Order()
    result = _apply_promotion(order=order, promotion_name=promotion_name)
    payload = {
        "promotion_name": result.promotion_name,
        "subtotal_paise": result.subtotal_paise,
        "discount_paise": result.discount_paise,
        "total_paise": result.total_paise,
        "message": result.message,
    }
    return Command(update={
        "order": result.order,
        "messages": [ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)],
    })


@tool
def swap_meal_item(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    meal_line_id: str,
    new_item_name: str,
) -> Command:
    """Break apart a meal line and swap one component for an á la carte item.

    Use this when the customer wants to change ONE part of an already-added
    meal (e.g. "make the coke a large" after they added Regular Meal). The
    meal is decomposed into its individual items; the component whose
    category matches `new_item_name` (drink vs side) is replaced with
    `new_item_name`. The customer then pays á la carte for those items,
    NOT the bundled next-size meal price.

    Do NOT use this when the customer wants to upgrade the whole meal
    (e.g. "make it a large meal") — for that, call update_order with
    line_id=<meal line> and item_name="Large Meal" to swap the bundle.

    Args:
        meal_line_id: The line_id of the existing meal (combo) line.
        new_item_name: Exact menu item name to swap in (e.g. "Large Coke",
            "Large Fries"). Must match the category of exactly one component
            of the meal.
    """
    order: Order = state.get("order") or Order()
    result = _swap_meal_item(
        order=order,
        meal_line_id=meal_line_id,
        new_item_name=new_item_name,
    )
    added_line_ids = set(result.added_line_ids)
    payload = {
        "removed_line_id": result.removed_line_id,
        "added_line_ids": result.added_line_ids,
        "message": result.message,
        "order_total_paise": result.order.total_paise,
        "line_count": len(result.order.lines),
        "added_lines": [
            _line_snapshot(l) for l in result.order.lines if l.line_id in added_line_ids
        ],
    }
    return Command(update={
        "order": result.order,
        "messages": [ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)],
    })


@tool
def submit_order(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Finalize the customer's order and send it to the kitchen.

    Only call this AFTER you have read back the order with confirm_order and
    the customer has explicitly confirmed (e.g. "yes", "place it", "that's
    right").
    """
    order: Order = state.get("order") or Order()
    result = _submit_order(order)
    payload = {
        "order_id": result.order_id,
        "total_paise": result.total_paise,
        "line_count": result.line_count,
        "message": result.message,
    }
    return Command(update={
        "submitted_order_id": result.order_id,
        "messages": [ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)],
    })


@tool
def cancel_order(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    reason: str = "customer cancelled",
) -> Command:
    """Cancel any in-flight order and END the conversation.

    Use this when:
      - The customer explicitly cancels ("cancel my order", "never mind",
        "I changed my mind").
      - The customer says goodbye / wraps up without confirming the order.
      - The customer otherwise indicates they're done without ordering.

    After this tool runs, the conversation ends. Include a brief farewell in
    your reply ("No worries — drive safe!"). There will be no more turns.

    Do NOT call this after submit_order has already succeeded — that session
    is already ending naturally.

    Args:
        reason: Short, human-readable reason (e.g. "customer cancelled",
            "customer left without ordering").
    """
    order: Order = state.get("order") or Order()
    result = _cancel_order(order=order, reason=reason)
    payload = {
        "cleared_line_count": result.cleared_line_count,
        "reason": result.reason,
        "message": result.message,
    }
    return Command(update={
        "order": Order(),
        "session_ended": True,
        "messages": [ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)],
    })


TOOLS = [
    query_menu, query_promotions,
    update_order, swap_meal_item, apply_promotion,
    confirm_order, submit_order, cancel_order,
]
