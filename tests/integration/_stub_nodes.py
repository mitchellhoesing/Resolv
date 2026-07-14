"""Stub node implementations for graph-topology tests.

These keep the LangGraph cycle tests independent of Docker, network, and
git; production wiring lives in `resolv.core.app.build_production_graph`.
"""

from __future__ import annotations

from typing import Any

from resolv.core.state import BlackboardState, IterationRecord


def stub_context_broker(state: BlackboardState) -> dict[str, Any]:
    return {}


def stub_coder(state: BlackboardState) -> dict[str, Any]:
    return {
        "current_diff": "--- a/stub\n+++ b/stub\n",
        "iteration": state.iteration + 1,
        "test_status": "PENDING",
        "test_output": None,
    }


def stub_test_runner(state: BlackboardState) -> dict[str, Any]:
    record = IterationRecord(
        iteration=state.iteration,
        diff=state.current_diff,
        test_status="PASSED",
        test_output="stub: 0 passed",
    )
    return {
        "test_status": "PASSED",
        "test_output": "stub: 0 passed",
        "history": [*state.history, record],
    }


def stub_deliver(state: BlackboardState) -> dict[str, Any]:
    return {}
