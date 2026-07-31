"""LangGraph workflow assembly.

The graph wires:

    START -> context_broker -> env_installer -> coder -> test_runner -> gate
    gate -> deliver -> END                          (tests PASSED)
    gate -> END                                     (stall — caller reports the failure)

The coder agent runs its own edit -> test -> fix cycle in one session, so the
graph is acyclic: a FAILED verdict ends the run for a human to triage rather
than starting another attempt.

Node functions are required arguments so tests can wire stubs and the
production builder (`resolv.core.app.build_production_graph`) wires real
implementations.

The compiled graph is always checkpointed — on disk when a `checkpointer` is
supplied, in memory otherwise — so every call must pass a run config containing
a `thread_id` (see `resolv.main.thread_id_for`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
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


def sqlite_checkpointer(database_path: Path) -> SqliteSaver:
    """Durable checkpointer whose database outlives the process that wrote it.

    Production points this inside the mounted log directory, so a finished
    container's state history stays queryable from the host. The connection is
    left open for the life of the process, which for a per-issue container is
    the life of the run.
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: LangGraph may touch the connection from its own
    # worker threads, and the run owns the database exclusively either way.
    connection = sqlite3.connect(str(database_path), check_same_thread=False)
    checkpointer = SqliteSaver(connection, serde=_CHECKPOINT_SERDE)
    checkpointer.setup()
    return checkpointer


GATE_DELIVER = "deliver"
GATE_STALL = "stall"


def gate_router(state: BlackboardState) -> str:
    """Route on the authoritative verdict: deliver on PASSED, otherwise stall."""
    decision = GATE_DELIVER if state.test_status == "PASSED" else GATE_STALL
    log_event(f"[gate] {decision} (test {state.test_status})")
    return decision


def build_graph(
    *,
    context_broker_fn: NodeFn,
    env_installer_fn: NodeFn,
    coder_fn: NodeFn,
    test_runner_fn: NodeFn,
    deliver_fn: NodeFn,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
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
        gate_router,
        {
            GATE_DELIVER: "deliver",
            GATE_STALL: END,
        },
    )
    graph.add_edge("deliver", END)

    # The checkpointer snapshots the Blackboard after every super-step, which is
    # what makes `get_state` / `get_state_history` available for inspection.
    # Callers must supply a `thread_id` in their run config.
    # Default is ephemeral: only production wants a database on disk.
    return graph.compile(
        checkpointer=checkpointer or InMemorySaver(serde=_CHECKPOINT_SERDE)
    )
