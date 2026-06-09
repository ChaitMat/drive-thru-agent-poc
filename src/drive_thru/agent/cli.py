"""Text-mode REPL for the Highway Bites drive-thru agent.

Run:
    .venv/bin/python -m drive_thru.agent.cli           # normal
    .venv/bin/python -m drive_thru.agent.cli -v        # verbose: stream node trace + state

Requires OPENAI_API_KEY in the environment (or a .env file at the repo root).

Each user input is one drive-thru turn. State persists for the session via
LangGraph's MemorySaver. Type 'reset' to start a fresh session, 'order' to
peek at the current order without prompting the LLM, or Ctrl-D / empty line
to exit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from drive_thru.agent.graph import build_graph
from drive_thru.order_state import Order


# ---------- formatting helpers ----------

def _print_agent_message(message) -> None:
    content = (message.content or "").strip()
    if content:
        print(f"\n🍔 Agent: {content}\n")


def _print_order(order: Order) -> None:
    if not order.lines:
        print("(order is empty)")
        return
    for line in order.lines:
        mods = f" [{', '.join(m.name for m in line.modifications)}]" if line.modifications else ""
        print(f"  {line.line_id}  {line.quantity} x {line.name}{mods}  "
              f"= ₹{line.line_total_paise / 100:.2f}")
    print(f"  TOTAL: ₹{order.total_paise / 100:.2f}")


def _hr(label: str = "") -> None:
    if label:
        print(f"\n  ── {label} " + "─" * (54 - len(label)))
    else:
        print("  " + "─" * 60)


# ---------- verbose-mode rendering ----------

def _summarize_tool_result(content: str) -> str:
    """One-line summary of a tool's JSON-serialized result.

    Our wrappers produce dicts with a `message`/`spoken_summary` field; query
    tools return lists. Falls back to a truncated raw preview.
    """
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content[:100] + ("…" if len(content) > 100 else "")

    if isinstance(parsed, list):
        if not parsed:
            return "[] (0 results)"
        first_name = parsed[0].get("name", "?") if isinstance(parsed[0], dict) else str(parsed[0])
        return f"{len(parsed)} result(s) — e.g. {first_name!r}"

    if isinstance(parsed, dict):
        for key in ("message", "spoken_summary"):
            if key in parsed and isinstance(parsed[key], str):
                return parsed[key]
        if "order_id" in parsed:
            return (
                f"order_id={parsed['order_id']}, "
                f"total=₹{parsed.get('total_paise', 0) / 100:.2f}"
            )
        return json.dumps(parsed, default=str)[:100]

    return str(parsed)[:100]


def _fmt_args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _print_node_update(node_name: str, update: dict[str, Any]) -> None:
    """Render one node's contribution to state in verbose mode."""
    label = f"[{node_name}]"

    for msg in update.get("messages", []) or []:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                print(f"  {label} 🧠 LLM → {len(msg.tool_calls)} tool call(s):")
                for tc in msg.tool_calls:
                    print(f"           ↪ {tc['name']}({_fmt_args(tc.get('args', {}))})")
            else:
                preview = (msg.content or "").strip().splitlines()[0] if msg.content else "(no content)"
                if len(preview) > 100:
                    preview = preview[:100] + "…"
                print(f"  {label} 💬 LLM reply: {preview}")
        elif isinstance(msg, ToolMessage):
            status = " (error)" if getattr(msg, "status", None) == "error" else ""
            print(f"  {label} ⚙️  {msg.name}{status} → {_summarize_tool_result(msg.content)}")

    if "order" in update:
        order = update["order"]
        if isinstance(order, Order):
            print(f"  {label} 📦 order updated: {len(order.lines)} line(s), ₹{order.total_paise/100:.2f}")
    if update.get("submitted_order_id") is not None:
        print(f"  {label} ✅ submitted_order_id = {update['submitted_order_id']}")
    if update.get("session_ended"):
        print(f"  {label} 🚪 session_ended = True")


def _print_state_snapshot(state: dict[str, Any]) -> None:
    print("\n  📊 State after turn:")
    order = state.get("order") or Order()
    print(f"     order: {len(order.lines)} line(s), ₹{order.total_paise/100:.2f}")
    for line in order.lines:
        mods = f" [{', '.join(m.name for m in line.modifications)}]" if line.modifications else ""
        print(f"       {line.line_id}  {line.quantity} x {line.name}{mods}  "
              f"₹{line.line_total_paise/100:.2f}")
    if not order.lines:
        print("       (empty)")
    print(f"     submitted_order_id: {state.get('submitted_order_id')}")
    print(f"     session_ended: {state.get('session_ended', False)}")
    print(f"     messages: {len(state.get('messages', []))} in history")


# ---------- turn driver ----------

def _run_turn_quiet(app, update: dict, config: dict) -> dict:
    result = app.invoke(update, config=config)
    _print_agent_message(result["messages"][-1])
    return result


def _run_turn_verbose(app, update: dict, config: dict) -> dict:
    _hr("agent trace")
    for chunk in app.stream(update, config=config, stream_mode="updates"):
        for node_name, node_update in chunk.items():
            _print_node_update(node_name, node_update)
    final_state = app.get_state(config).values
    _print_state_snapshot(final_state)
    _hr()
    _print_agent_message(final_state["messages"][-1])
    return final_state


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Highway Bites drive-thru text REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Stream the node-by-node trace: which tool was called with which "
             "args, what came back, and the LangGraph state after each turn.",
    )
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)

    app = build_graph()
    thread_id = f"cli-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    first_turn = True

    mode = "verbose" if args.verbose else "normal"
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    print(f"Highway Bites drive-thru — {mode} mode (model={model}, thread={thread_id})")
    print("Type your order, 'order' to peek at the cart, 'reset' to start over, blank to quit.\n")

    run_turn = _run_turn_verbose if args.verbose else _run_turn_quiet

    while True:
        try:
            user = input("👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user:
            return
        if user.lower() == "reset":
            thread_id = f"cli-{uuid.uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": thread_id}}
            first_turn = True
            print(f"(new session: {thread_id})\n")
            continue
        if user.lower() == "order":
            snapshot = app.get_state(config).values if not first_turn else {}
            _print_order(snapshot.get("order", Order()))
            continue

        update = {"messages": [HumanMessage(content=user)]}
        if first_turn:
            update["order"] = Order()
            update["submitted_order_id"] = None
            update["session_ended"] = False
            first_turn = False

        result = run_turn(app, update, config)

        if result.get("submitted_order_id"):
            print(f"✅ Order #{result['submitted_order_id']} placed. Drive forward.\n")
            return
        if result.get("session_ended"):
            print("👋 Session ended.\n")
            return


if __name__ == "__main__":
    main()
