"""No-LLM smoke tests: the graph compiles and the 5 tool wrappers are wired.

The deeper InjectedState + Command behavior requires a live Pregel runtime,
which is exercised end-to-end via the CLI REPL (and, later, the eval harness).
"""

import os

from drive_thru.agent.graph import build_graph
from drive_thru.agent.tools import TOOLS


def test_graph_compiles_without_llm():
    os.environ.setdefault("OPENAI_API_KEY", "sk-dummy-for-compile")
    app = build_graph()
    nodes = set(app.get_graph().nodes)
    assert {"agent", "tools"}.issubset(nodes)


def test_all_tools_present():
    names = {t.name for t in TOOLS}
    assert names == {
        "query_menu", "query_promotions",
        "update_order", "swap_meal_item", "apply_promotion",
        "confirm_order", "submit_order",
        "cancel_order",
    }


def test_each_tool_has_docstring():
    """The docstring is what the LLM reads to decide when to call each tool."""
    for tool in TOOLS:
        assert tool.description, f"{tool.name} is missing a description"
        assert len(tool.description) > 50, f"{tool.name} description is too thin"
