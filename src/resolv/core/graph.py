"""LangGraph workflow assembly.

The graph wires:

    START -> context_broker -> coder -> test_runner -> gate
    gate -> deliver -> END                          (tests PASSED)
    gate -> coder                                   (loop with feedback, iteration < max)
    gate -> END                                     (stall — LoopStallError logged by caller)

Node functions are required arguments so tests can wire stubs and the
production builder (`resolv.core.app.build_production_graph`) wires real
implementations.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from resolv.core.state import BlackboardState

NodeFn = Callable[[BlackboardState], dict[str, Any]]

GATE_DELIVER = "deliver"
GATE_LOOP = "loop"
GATE_STALL = "stall"


def _make_gate_router(max_iterations: int) -> Callable[[BlackboardState], str]:
    def gate_router(state: BlackboardState) -> str:
        if state.test_status == "PASSED":
            return GATE_DELIVER
        if state.iteration >= max_iterations:
            return GATE_STALL
        return GATE_LOOP

    return gate_router


def build_graph(
    *,
    context_broker_fn: NodeFn,
    coder_fn: NodeFn,
    test_runner_fn: NodeFn,
    deliver_fn: NodeFn,
    max_iterations: int = 5,
) -> CompiledStateGraph:
    graph: StateGraph = StateGraph(BlackboardState)

    # LangGraph's add_node has heavily overloaded generic signatures that
    # don't match a plain Callable[[BlackboardState], dict[str, Any]]; the
    # calls work at runtime.
    graph.add_node("context_broker", context_broker_fn)  # type: ignore[call-overload]
    graph.add_node("coder", coder_fn)  # type: ignore[call-overload]
    graph.add_node("test_runner", test_runner_fn)  # type: ignore[call-overload]
    graph.add_node("deliver", deliver_fn)  # type: ignore[call-overload]

    graph.add_edge(START, "context_broker")
    graph.add_edge("context_broker", "coder")
    graph.add_edge("coder", "test_runner")
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
