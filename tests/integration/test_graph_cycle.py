"""Integration tests for the LangGraph topology with stub nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from resolv.core.graph import build_graph, sqlite_checkpointer
from resolv.core.state import BlackboardState, IssueRef
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


def _failing_tests(state: BlackboardState) -> dict[str, Any]:
    return {"test_status": "FAILED", "test_output": "forced failure"}


def test_happy_path_reaches_deliver(initial_state: BlackboardState) -> None:
    app = build_graph(**_default_wiring())
    final = app.invoke(initial_state, config=_config())

    assert final["test_status"] == "PASSED"
    assert final["test_output"] == "stub: 0 passed"


def test_failed_tests_end_the_run_without_returning_to_coder(
    initial_state: BlackboardState,
) -> None:
    """The invariant that replaced the retry loop: FAILED routes to END.

    The coder agent runs its own edit/test cycle, so a failure here is final and
    the graph must not start a second attempt.
    """
    coder_calls: list[str] = []

    def counting_coder(state: BlackboardState) -> dict[str, Any]:
        coder_calls.append(state.test_status)
        return stub_coder(state)

    config = _config()
    app = build_graph(
        **_default_wiring(coder_fn=counting_coder, test_runner_fn=_failing_tests)
    )
    final = app.invoke(initial_state, config=config)

    assert final["test_status"] == "FAILED"
    assert coder_calls == ["PENDING"]
    executed_path = _executed_path(app, config)
    assert executed_path == ["context_broker", "env_installer", "coder", "test_runner"]
    assert "deliver" not in executed_path


def _executed_path(app: Any, config: dict[str, Any]) -> list[str]:
    """The nodes the run entered, oldest first, read back from the checkpointer."""
    snapshots = list(reversed(list(app.get_state_history(config))))
    return [
        snapshot.next[0]
        for snapshot in snapshots
        if snapshot.next and snapshot.next[0] != "__start__"
    ]


def test_sqlite_checkpointer_outlives_the_graph_that_wrote_it(
    initial_state: BlackboardState, tmp_path: Path
) -> None:
    """A finished run must stay queryable without the original graph object."""
    database = tmp_path / "checkpoints.sqlite"
    config = _config()

    writer = build_graph(
        checkpointer=sqlite_checkpointer(database),
        **_default_wiring(),
    )
    writer.invoke(initial_state, config=config)
    del writer

    # A different graph, built from scratch against the same database.
    reader = build_graph(
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
    assert isinstance(snapshots[-1].values["issue"], IssueRef)


def test_gate_logs_the_stall_decision(
    initial_state: BlackboardState, mocker: MockerFixture
) -> None:
    """The gate's branch is otherwise invisible — it must appear in the run log."""
    log_mock = mocker.patch("resolv.core.graph.log_event")

    app = build_graph(**_default_wiring(test_runner_fn=_failing_tests))
    app.invoke(initial_state, config=_config())

    assert [call.args[0] for call in log_mock.call_args_list] == [
        "[gate] stall (test FAILED)"
    ]


def test_gate_logs_the_deliver_decision(
    initial_state: BlackboardState, mocker: MockerFixture
) -> None:
    log_mock = mocker.patch("resolv.core.graph.log_event")

    app = build_graph(**_default_wiring())
    app.invoke(initial_state, config=_config())

    assert [call.args[0] for call in log_mock.call_args_list] == [
        "[gate] deliver (test PASSED)"
    ]


def test_state_history_exposes_every_node_boundary(
    initial_state: BlackboardState,
) -> None:
    """The checkpointer must expose intermediate state, not just the final result."""
    config = _config()
    app = build_graph(**_default_wiring())
    app.invoke(initial_state, config=config)

    snapshots = list(reversed(list(app.get_state_history(config))))
    assert snapshots, "checkpointer produced no snapshots"
    assert _executed_path(app, config) == [
        "context_broker",
        "env_installer",
        "coder",
        "test_runner",
        "deliver",
    ]

    # The pre-verdict PENDING state is still recoverable after the run passed.
    assert any(
        snapshot.values.get("test_status") == "PENDING" for snapshot in snapshots
    )
