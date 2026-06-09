"""LangGraph state for the drive-thru conversation."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from drive_thru.order_state import Order


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    order: Order
    submitted_order_id: int | None
    session_ended: bool
