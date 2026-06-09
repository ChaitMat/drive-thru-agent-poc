"""Compile the Highway Bites conversation graph.

Topology:

    START -> agent --tool_calls?--> tools --> agent --> END
                  \\-----no tool_calls----------> END

The `agent` node is the OpenAI LLM bound to the tools. The `tools` node is a
custom sequential dispatcher (NOT LangGraph's prebuilt ToolNode): when the
LLM emits multiple tool calls in one turn, ToolNode runs them concurrently
and concurrent `Command(update={"order": ...})` writes hit LangGraph's
LastValue channel and crash. Our dispatcher runs them one at a time,
threading the accumulated state through each call so each tool sees the
previous tool's writes — and only one write per state field reaches the
channel per step.

State persists across turns via a checkpointer keyed by `thread_id`, so each
drive-thru session is its own conversation history.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Callable, Literal

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from drive_thru.agent.prompts import SYSTEM_PROMPT
from drive_thru.agent.state import AgentState
from drive_thru.agent.tools import TOOLS


def _make_llm() -> ChatOpenAI:
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model, temperature=0.1).bind_tools(TOOLS)


def _agent_node(state: AgentState) -> dict:
    llm = _make_llm()
    response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]])
    return {"messages": [response]}


def _route_after_agent(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def _format_tool_error(e: Exception) -> str:
    """Turn a tool exception into a hint the LLM can recover from."""
    return (
        f"Tool error ({type(e).__name__}): {e}\n"
        "If this was a name lookup failure, call query_menu to find the exact "
        "item name and try again. Do not invent item names."
    )


def _make_sequential_tools_node(
    tools: list, error_handler: Callable[[Exception], str]
):
    """Build a tools node that runs tool calls one at a time.

    Each iteration sees the accumulated state from prior calls in the same
    turn, so two `update_order` calls hitting different lines compose cleanly
    instead of racing on the `order` channel.
    """
    tools_by_name = {t.name: t for t in tools}

    def tools_node(state: AgentState) -> dict[str, Any]:
        last_msg = state["messages"][-1]
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        if not tool_calls:
            return {}

        # Working copy of state that gets threaded through each tool call.
        # Reads see the most recent prior write within this turn.
        working: dict[str, Any] = {
            "messages": list(state["messages"]),
            "order": state.get("order"),
            "submitted_order_id": state.get("submitted_order_id"),
            "session_ended": state.get("session_ended", False),
        }
        # Messages produced *during* this turn — returned at the end.
        new_messages: list = []

        for tc in tool_calls:
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                new_messages.append(ToolMessage(
                    content=f"Unknown tool: {tc['name']!r}",
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    status="error",
                ))
                continue

            # Decide which kwargs to inject based on the underlying function's
            # signature. InjectedState / InjectedToolCallId are markers — at
            # runtime we just pass the values as regular kwargs.
            kwargs = dict(tc.get("args") or {})
            sig = inspect.signature(tool.func)
            if "state" in sig.parameters:
                kwargs["state"] = working
            if "tool_call_id" in sig.parameters:
                kwargs["tool_call_id"] = tc["id"]

            try:
                result = tool.func(**kwargs)
            except Exception as e:
                tm = ToolMessage(
                    content=error_handler(e),
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    status="error",
                )
                new_messages.append(tm)
                working["messages"] = working["messages"] + [tm]
                continue

            if isinstance(result, Command):
                for key, val in (result.update or {}).items():
                    if key == "messages":
                        # Backfill the tool name on ToolMessages emitted via
                        # Command — our wrappers don't set it, and a bare
                        # `name=None` reads as "None" in trace output.
                        for msg in val:
                            if isinstance(msg, ToolMessage) and not msg.name:
                                msg.name = tool.name
                        new_messages.extend(val)
                        working["messages"] = working["messages"] + list(val)
                    else:
                        working[key] = val
            else:
                content = result if isinstance(result, str) else json.dumps(result, default=str)
                tm = ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"])
                new_messages.append(tm)
                working["messages"] = working["messages"] + [tm]

        return {
            "messages": new_messages,
            "order": working["order"],
            "submitted_order_id": working["submitted_order_id"],
            "session_ended": working["session_ended"],
        }

    return tools_node


def build_graph(*, with_checkpointer: bool = True):
    builder = StateGraph(AgentState)
    builder.add_node("agent", _agent_node)
    builder.add_node("tools", _make_sequential_tools_node(TOOLS, _format_tool_error))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")

    checkpointer = MemorySaver() if with_checkpointer else None
    return builder.compile(checkpointer=checkpointer)
