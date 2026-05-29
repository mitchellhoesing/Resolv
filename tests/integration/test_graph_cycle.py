"""Integration tests for the LangGraph cycle with stub nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from resolv.core.graph import build_graph
from resolv.core.state import BlackboardState, IssueRef, IterationRecord
from tests.integration._stub_nodes import (
    stub_coder,
    stub_context_broker,
    stub_deliver,
    stub_test_runner,
)


@pytest.fixture
def initial_state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(
        owner="acme", repo="widgets", number=1, title="Trigger graph", body="", labels=()
    )
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def _default_wiring(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "context_broker_fn": stub_context_broker,
        "coder_fn": stub_coder,
        "test_runner_fn": stub_test_runner,
        "deliver_fn": stub_deliver,
    }
    defaults.update(overrides)
    return defaults


def test_happy_path_reaches_deliver(initial_state: BlackboardState) -> None:
    app = build_graph(max_iterations=5, **_default_wiring())
    final = app.invoke(initial_state)

    assert final["test_status"] == "PASSED"
    assert final["iteration"] == 1
    assert len(final["history"]) == 1
    assert final["history"][0].test_status == "PASSED"


def test_loop_terminates_on_max_iterations(initial_state: BlackboardState) -> None:
    def failing_tests(state: BlackboardState) -> dict[str, Any]:
        record = IterationRecord(
            iteration=state.iteration,
            diff=state.current_diff,
            test_status="FAILED",
            test_output="forced failure",
        )
        return {
            "test_status": "FAILED",
            "test_output": "forced failure",
            "history": [*state.history, record],
        }

    app = build_graph(max_iterations=3, **_default_wiring(test_runner_fn=failing_tests))
    final = app.invoke(initial_state)

    assert final["test_status"] == "FAILED"
    assert final["iteration"] == 3
    assert len(final["history"]) == 3


def test_loop_recovers_after_initial_failures(initial_state: BlackboardState) -> None:
    call_log: list[int] = []

    def flaky_tests(state: BlackboardState) -> dict[str, Any]:
        call_log.append(state.iteration)
        passed = state.iteration >= 2
        record = IterationRecord(
            iteration=state.iteration,
            diff=state.current_diff,
            test_status="PASSED" if passed else "FAILED",
            test_output="ok" if passed else "boom",
        )
        return {
            "test_status": "PASSED" if passed else "FAILED",
            "test_output": "ok" if passed else "boom",
            "history": [*state.history, record],
        }

    app = build_graph(max_iterations=5, **_default_wiring(test_runner_fn=flaky_tests))
    final = app.invoke(initial_state)

    assert final["test_status"] == "PASSED"
    assert final["iteration"] == 2
    assert call_log == [1, 2]
