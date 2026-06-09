"""Run one EvalCase against the live LangGraph agent.

Each case is driven through `build_graph()` against a fresh thread_id, so
state from one case can't leak into another. We use `app.stream()` to capture
each tool call as it happens — the captured list feeds the structural
assertions in `evals.cases`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage

from drive_thru.agent.graph import build_graph
from drive_thru.order_state import Order
from evals.cases import EvalCase


@dataclass
class CaseResult:
    case: EvalCase
    passed: bool
    failures: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    per_turn_latency_s: list[float] = field(default_factory=list)
    final_order: Order = field(default_factory=Order)
    submitted_order_id: int | None = None
    last_reply: str = ""
    error: str | None = None  # set when the run itself crashed


def run_case(case: EvalCase) -> CaseResult:
    app = build_graph()
    thread_id = f"eval-{case.case_id}-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": thread_id}}

    tool_calls: list[str] = []
    latencies: list[float] = []
    last_reply = ""
    first_turn = True

    try:
        for user_msg in case.user_messages:
            update: dict = {"messages": [HumanMessage(content=user_msg)]}
            if first_turn:
                update["order"] = Order()
                update["submitted_order_id"] = None
                update["session_ended"] = False
                first_turn = False

            start = time.perf_counter()
            for chunk in app.stream(update, config=config, stream_mode="updates"):
                for _node, node_update in chunk.items():
                    for msg in node_update.get("messages", []) or []:
                        if isinstance(msg, AIMessage):
                            for tc in (msg.tool_calls or []):
                                tool_calls.append(tc["name"])
                            if msg.content and not msg.tool_calls:
                                last_reply = msg.content
            latencies.append(time.perf_counter() - start)

        final_state = app.get_state(config).values
    except Exception as exc:
        return CaseResult(
            case=case,
            passed=False,
            failures=[f"Run crashed: {type(exc).__name__}: {exc}"],
            tool_calls=tool_calls,
            per_turn_latency_s=latencies,
            error=str(exc),
        )

    order: Order = final_state.get("order") or Order()
    submitted_id = final_state.get("submitted_order_id")

    failures = _check_assertions(
        case=case,
        order=order,
        tool_calls=tool_calls,
        final_state=final_state,
        last_reply=last_reply,
        submitted_id=submitted_id,
    )

    return CaseResult(
        case=case,
        passed=not failures,
        failures=failures,
        tool_calls=tool_calls,
        per_turn_latency_s=latencies,
        final_order=order,
        submitted_order_id=submitted_id,
        last_reply=last_reply,
    )


def _check_assertions(
    *,
    case: EvalCase,
    order: Order,
    tool_calls: list[str],
    final_state: dict,
    last_reply: str,
    submitted_id: int | None,
) -> list[str]:
    failures: list[str] = []

    # Lines
    if case.expected_lines is not None:
        actual = [(l.name, l.quantity, frozenset(m.name for m in l.modifications))
                  for l in order.lines]
        expected = [(el.name, el.quantity, frozenset(el.modifications))
                    for el in case.expected_lines]
        if sorted(actual) != sorted(expected):
            failures.append(
                "Order lines don't match.\n"
                f"        expected: {expected}\n"
                f"        actual:   {actual}"
            )

    # Tools required
    if case.expected_tools_called is not None:
        called = set(tool_calls)
        missing = case.expected_tools_called - called
        if missing:
            failures.append(
                f"Expected tools were never called: {sorted(missing)}. "
                f"Tools that ran: {tool_calls}"
            )

    # Tools forbidden
    if case.expected_tools_not_called is not None:
        forbidden = case.expected_tools_not_called & set(tool_calls)
        if forbidden:
            failures.append(
                f"Forbidden tools were called: {sorted(forbidden)}. "
                f"Full trace: {tool_calls}"
            )

    # Submit flag
    if case.expected_submit is not None:
        was_submitted = submitted_id is not None
        if case.expected_submit and not was_submitted:
            failures.append("Expected the order to be submitted, but it wasn't.")
        if not case.expected_submit and was_submitted:
            failures.append(
                f"Expected NOT to submit, but order #{submitted_id} was created."
            )

    # Custom check
    if case.custom_check is not None:
        try:
            failures.extend(case.custom_check(order, tool_calls, final_state, last_reply))
        except Exception as exc:
            failures.append(f"custom_check raised: {type(exc).__name__}: {exc}")

    return failures
