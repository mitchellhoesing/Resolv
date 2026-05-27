"""LangGraph workflow assembly.

The graph wires:

    START -> context_broker -> coder -> coderabbit_qa -> test_runner -> gate
    gate -> deliver -> END                          (QA APPROVED and tests PASSED)
    gate -> coder                                   (loop with feedback, iteration < max)
    gate -> END                                     (stall — LoopStallError logged by caller)

Node functions are injectable to support unit/integration tests that
need to force specific QA / test outcomes.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from resolv.core.state import BlackboardState
from resolv.nodes.coder import coder_node
from resolv.nodes.coderabbit_qa import coderabbit_qa_node
from resolv.nodes.context_broker import context_broker_node
from resolv.nodes.deliver import deliver_node
from resolv.nodes.test_runner import test_runner_node

NodeFn = Callable[[BlackboardState], dict[str, Any]]

GATE_DELIVER = "deliver"
GATE_LOOP = "loop"
GATE_STALL = "stall"


def _make_gate_router(max_iterations: int) -> Callable[[BlackboardState], str]:
    def gate_router(state: BlackboardState) -> str:
        if state.qa_status == "APPROVED" and state.test_status == "PASSED":
            return GATE_DELIVER
        if state.iteration >= max_iterations:
            return GATE_STALL
        return GATE_LOOP

    return gate_router


def build_graph(
    max_iterations: int = 5,
    *,
    context_broker_fn: NodeFn = context_broker_node,
    coder_fn: NodeFn = coder_node,
    coderabbit_qa_fn: NodeFn = coderabbit_qa_node,
    test_runner_fn: NodeFn = test_runner_node,
    deliver_fn: NodeFn = deliver_node,
) -> CompiledStateGraph:
    graph: StateGraph = StateGraph(BlackboardState)

    graph.add_node("context_broker", context_broker_fn)
    graph.add_node("coder", coder_fn)
    graph.add_node("coderabbit_qa", coderabbit_qa_fn)
    graph.add_node("test_runner", test_runner_fn)
    graph.add_node("deliver", deliver_fn)

    graph.add_edge(START, "context_broker")
    graph.add_edge("context_broker", "coder")
    graph.add_edge("coder", "coderabbit_qa")
    graph.add_edge("coderabbit_qa", "test_runner")
    graph.add_conditional_edges(
        "test_runner",
        _make_gate_router(max_iterations),
        {
            GATE_DELIVER: "deliver",
            GATE_LOOP: "coder",
            GATE_STALL: END,
        },
    )
    graph.add_edge("deliver", END)

    return graph.compile()
