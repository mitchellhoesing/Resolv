"""Integration tests for the LangGraph cycle with stub nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from resolv.core.graph import build_graph
from resolv.core.state import BlackboardState, IssueRef


@pytest.fixture
def initial_state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(
        owner="acme",
        repo="widgets",
        number=1,
        title="Trigger graph",
        body="",
        labels=(),
    )
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def test_happy_path_reaches_deliver(initial_state: BlackboardState) -> None:
    app = build_graph(max_iterations=5)
    final = app.invoke(initial_state)

    assert final["qa_status"] == "APPROVED"
    assert final["test_status"] == "PASSED"
    assert final["iteration"] == 1
    assert len(final["history"]) == 1
    assert final["history"][0].test_status == "PASSED"


def test_loop_terminates_on_max_iterations(initial_state: BlackboardState) -> None:
    def rejecting_qa(state: BlackboardState) -> dict[str, Any]:
        return {"qa_status": "REJECTED", "qa_findings": ["forced reject"]}

    app = build_graph(max_iterations=3, coderabbit_qa_fn=rejecting_qa)
    final = app.invoke(initial_state)

    assert final["qa_status"] == "REJECTED"
    assert final["iteration"] == 3
    assert len(final["history"]) == 3


def test_loop_recovers_after_initial_failures(initial_state: BlackboardState) -> None:
    call_log: list[int] = []

    def flaky_tests(state: BlackboardState) -> dict[str, Any]:
        call_log.append(state.iteration)
        passed = state.iteration >= 2
        from resolv.core.state import IterationRecord

        record = IterationRecord(
            iteration=state.iteration,
            diff=state.current_diff,
            qa_status=state.qa_status,
            qa_findings=tuple(state.qa_findings),
            test_status="PASSED" if passed else "FAILED",
            test_output="ok" if passed else "boom",
        )
        return {
            "test_status": "PASSED" if passed else "FAILED",
            "test_output": "ok" if passed else "boom",
            "history": [*state.history, record],
        }

    app = build_graph(max_iterations=5, test_runner_fn=flaky_tests)
    final = app.invoke(initial_state)

    assert final["test_status"] == "PASSED"
    assert final["iteration"] == 2
    assert call_log == [1, 2]
