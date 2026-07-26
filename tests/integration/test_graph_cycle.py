"""Integration tests for the LangGraph cycle with stub nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from resolv.core.graph import build_graph, sqlite_checkpointer
from resolv.core.state import BlackboardState, IssueRef, IterationRecord
from tests.integration._stub_nodes import (
    stub_coder,
    stub_context_broker,
    stub_deliver,
    stub_env_installer,
    stub_test_runner,
)


@pytest.fixture
def initial_state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(
        owner="acme", repo="widgets", number=1, title="Trigger graph", body="", labels=()
    )
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def _config(thread_id: str = "acme/widgets#1") -> dict[str, Any]:
    """Run config for the checkpointed graph; a thread id is mandatory."""
    return {"configurable": {"thread_id": thread_id}}


def _default_wiring(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "context_broker_fn": stub_context_broker,
        "env_installer_fn": stub_env_installer,
        "coder_fn": stub_coder,
        "test_runner_fn": stub_test_runner,
        "deliver_fn": stub_deliver,
    }
    defaults.update(overrides)
    return defaults


def test_happy_path_reaches_deliver(initial_state: BlackboardState) -> None:
    app = build_graph(max_iterations=5, **_default_wiring())
    final = app.invoke(initial_state, config=_config())

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
    final = app.invoke(initial_state, config=_config())

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
    final = app.invoke(initial_state, config=_config())

    assert final["test_status"] == "PASSED"
    assert final["iteration"] == 2
    assert call_log == [1, 2]


def test_sqlite_checkpointer_outlives_the_graph_that_wrote_it(
    initial_state: BlackboardState, tmp_path: Path
) -> None:
    """A finished run must stay queryable without the original graph object."""
    database = tmp_path / "checkpoints.sqlite"
    config = _config()

    writer = build_graph(
        max_iterations=5,
        checkpointer=sqlite_checkpointer(database),
        **_default_wiring(),
    )
    writer.invoke(initial_state, config=config)
    del writer

    # A different graph, built from scratch against the same database.
    reader = build_graph(
        max_iterations=5,
        checkpointer=sqlite_checkpointer(database),
        **_default_wiring(),
    )
    snapshots = list(reversed(list(reader.get_state_history(config))))

    assert [s.next[0] for s in snapshots if s.next and s.next[0] != "__start__"] == [
        "context_broker",
        "env_installer",
        "coder",
        "test_runner",
        "deliver",
    ]
    # Custom types survive the database round-trip, not just plain fields.
    final_values = snapshots[-1].values
    assert isinstance(final_values["issue"], IssueRef)
    assert isinstance(final_values["history"][0], IterationRecord)


def test_gate_logs_each_routing_decision(
    initial_state: BlackboardState, mocker: MockerFixture
) -> None:
    """The gate's branch is otherwise invisible — it must appear in the run log."""
    log_mock = mocker.patch("resolv.core.graph.log_event")

    def failing_tests(state: BlackboardState) -> dict[str, Any]:
        return {"test_status": "FAILED", "test_output": "boom"}

    app = build_graph(max_iterations=2, **_default_wiring(test_runner_fn=failing_tests))
    app.invoke(initial_state, config=_config())

    gate_messages = [call.args[0] for call in log_mock.call_args_list]
    assert gate_messages == [
        "[gate] loop (iteration 1/2, test FAILED)",
        "[gate] stall (iteration 2/2, test FAILED)",
    ]


def test_gate_logs_the_deliver_decision(
    initial_state: BlackboardState, mocker: MockerFixture
) -> None:
    log_mock = mocker.patch("resolv.core.graph.log_event")

    app = build_graph(max_iterations=5, **_default_wiring())
    app.invoke(initial_state, config=_config())

    assert [call.args[0] for call in log_mock.call_args_list] == [
        "[gate] deliver (iteration 1/5, test PASSED)"
    ]


def test_state_history_exposes_every_node_boundary(
    initial_state: BlackboardState,
) -> None:
    """The checkpointer must expose intermediate state, not just the final result."""

    def flaky_tests(state: BlackboardState) -> dict[str, Any]:
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

    config = _config()
    app = build_graph(max_iterations=5, **_default_wiring(test_runner_fn=flaky_tests))
    app.invoke(initial_state, config=config)

    # get_state_history yields newest-first; reverse to read the run in order.
    snapshots = list(reversed(list(app.get_state_history(config))))
    assert snapshots, "checkpointer produced no snapshots"

    # Each snapshot's `next` names the node about to run, so the sequence traces
    # the executed path — including the coder -> test_runner -> coder loop.
    executed_path = [
        snapshot.next[0]
        for snapshot in snapshots
        if snapshot.next and snapshot.next[0] != "__start__"
    ]
    assert executed_path == [
        "context_broker",
        "env_installer",
        "coder",
        "test_runner",
        "coder",
        "test_runner",
        "deliver",
    ]

    # The failed first iteration is still recoverable even though the run passed.
    assert any(
        snapshot.values.get("test_status") == "FAILED" for snapshot in snapshots
    )
