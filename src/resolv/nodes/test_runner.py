"""Test Runner node — detects framework and runs tests in the sandbox.

Phase 2 stub: marks tests as PASSED and snapshots the iteration into
history. Real detection + Docker dispatch lands in Phase 4.
"""

from __future__ import annotations

from typing import Any

from resolv.core.state import BlackboardState, IterationRecord


def test_runner_node(state: BlackboardState) -> dict[str, Any]:
    record = IterationRecord(
        iteration=state.iteration,
        diff=state.current_diff,
        qa_status=state.qa_status,
        qa_findings=tuple(state.qa_findings),
        test_status="PASSED",
        test_output="stub: 0 passed",
    )
    return {
        "test_status": "PASSED",
        "test_output": "stub: 0 passed",
        "history": [*state.history, record],
    }
