"""LangGraph workflow assembly.

The graph wires:

    START -> context_broker -> env_installer -> coder -> test_runner -> gate
    gate -> deliver -> END                          (tests PASSED)
    gate -> coder                                   (loop with feedback, iteration < max)
    gate -> END                                     (stall — LoopStallError logged by caller)

Node functions are required arguments so tests can wire stubs and the
production builder (`resolv.core.app.build_production_graph`) wires real
implementations.

The compiled graph carries an in-memory checkpointer, so every call must pass
a run config containing a `thread_id` (see `resolv.main.thread_id_for`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from resolv.core.state import BlackboardState, IssueRef, IterationRecord
from resolv.utils.run_log import log_event

NodeFn = Callable[[BlackboardState], dict[str, Any]]

# Register the Blackboard's own types with the checkpoint serializer. Without an
# explicit allowlist LangGraph applies a permissive default that allows *any*
# importable type and warns once per type per run; under its future default these
# types deserialize to plain dicts instead of themselves.
_CHECKPOINT_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[BlackboardState, IssueRef, IterationRecord]
)

GATE_DELIVER = "deliver"
GATE_LOOP = "loop"
GATE_STALL = "stall"


def _make_gate_router(max_iterations: int) -> Callable[[BlackboardState], str]:
    def gate_router(state: BlackboardState) -> str:
        if state.test_status == "PASSED":
            decision = GATE_DELIVER
        elif state.iteration >= max_iterations:
            decision = GATE_STALL
        else:
            decision = GATE_LOOP
        log_event(
            f"[gate] {decision} (iteration {state.iteration}/{max_iterations}, "
            f"test {state.test_status})"
        )
        return decision

    return gate_router


def build_graph(
    *,
    context_broker_fn: NodeFn,
    env_installer_fn: NodeFn,
    coder_fn: NodeFn,
    test_runner_fn: NodeFn,
    deliver_fn: NodeFn,
    max_iterations: int = 3,
) -> CompiledStateGraph:
    graph: StateGraph = StateGraph(BlackboardState)

    # LangGraph's add_node has heavily overloaded generic signatures that
    # don't match a plain Callable[[BlackboardState], dict[str, Any]]; the
    # calls work at runtime.
    graph.add_node("context_broker", context_broker_fn)  # type: ignore[call-overload]
    graph.add_node("env_installer", env_installer_fn)  # type: ignore[call-overload]
    graph.add_node("coder", coder_fn)  # type: ignore[call-overload]
    graph.add_node("test_runner", test_runner_fn)  # type: ignore[call-overload]
    graph.add_node("deliver", deliver_fn)  # type: ignore[call-overload]

    graph.add_edge(START, "context_broker")
    graph.add_edge("context_broker", "env_installer")
    graph.add_edge("env_installer", "coder")
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

    # The checkpointer snapshots the Blackboard after every super-step, which is
    # what makes `get_state` / `get_state_history` available for inspection.
    # Callers must supply a `thread_id` in their run config.
    return graph.compile(checkpointer=InMemorySaver(serde=_CHECKPOINT_SERDE))
