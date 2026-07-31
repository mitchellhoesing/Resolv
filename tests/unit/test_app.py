"""Unit tests for the production graph wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.config import Settings
from resolv.core.app import (
    build_production_graph,
    checkpoint_database_path,
    log_node_boundaries,
)
from resolv.core.state import BlackboardState


def _patched_settings(**overrides: object) -> Settings:
    base = Settings(github_token=SecretStr("ghp_fake"))
    return base.model_copy(update=overrides)


def test_build_production_graph_wires_all_nodes(mocker: MockerFixture) -> None:
    mocker.patch("resolv.core.app.GitHubClient", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeBackend", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeClient", return_value=MagicMock())
    fake_build_graph = mocker.patch(
        "resolv.core.app.build_graph", return_value=MagicMock()
    )

    settings = _patched_settings()
    build_production_graph(settings)

    fake_build_graph.assert_called_once()
    kwargs = fake_build_graph.call_args.kwargs
    assert set(kwargs) == {
        "context_broker_fn",
        "env_installer_fn",
        "coder_fn",
        "test_runner_fn",
        "deliver_fn",
        "checkpointer",
    }
    # Production checkpoints to disk so a finished run stays queryable.
    assert isinstance(kwargs["checkpointer"], SqliteSaver)
    assert checkpoint_database_path().is_file()
    for key in (
        "context_broker_fn",
        "env_installer_fn",
        "coder_fn",
        "test_runner_fn",
        "deliver_fn",
    ):
        assert callable(kwargs[key])


def test_build_production_graph_wraps_every_node_with_logging(
    mocker: MockerFixture,
) -> None:
    mocker.patch("resolv.core.app.GitHubClient", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeBackend", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeClient", return_value=MagicMock())
    mocker.patch("resolv.core.app.build_graph", return_value=MagicMock())
    wrapper_mock = mocker.patch(
        "resolv.core.app.log_node_boundaries", side_effect=lambda name, fn: fn
    )

    build_production_graph(_patched_settings())

    assert [call.args[0] for call in wrapper_mock.call_args_list] == [
        "context_broker",
        "env_installer",
        "coder",
        "test_runner",
        "deliver",
    ]


def test_log_node_boundaries_records_entry_and_written_keys(
    sample_state: BlackboardState, mocker: MockerFixture
) -> None:
    log_mock = mocker.patch("resolv.core.app.log_event")

    def node(state: BlackboardState) -> dict[str, object]:
        return {"test_status": "PENDING", "current_diff": "--- a\n"}

    update = log_node_boundaries("coder", node)(sample_state)

    assert update == {"test_status": "PENDING", "current_diff": "--- a\n"}
    entry_message, exit_message = (call.args[0] for call in log_mock.call_args_list)
    assert entry_message == f"[coder] enter {sample_state.summary()}"
    # Keys are sorted so the line is stable across runs.
    assert exit_message == "[coder] exit wrote current_diff, test_status"


def test_log_node_boundaries_marks_nodes_that_write_nothing(
    sample_state: BlackboardState, mocker: MockerFixture
) -> None:
    log_mock = mocker.patch("resolv.core.app.log_event")

    log_node_boundaries("env_installer", lambda state: {})(sample_state)

    assert log_mock.call_args_list[-1].args[0] == (
        "[env_installer] exit wrote (no changes)"
    )


def test_log_node_boundaries_does_not_swallow_node_failures(
    sample_state: BlackboardState, mocker: MockerFixture
) -> None:
    mocker.patch("resolv.core.app.log_event")

    def failing_node(state: BlackboardState) -> dict[str, object]:
        raise RuntimeError("node blew up")

    with pytest.raises(RuntimeError, match="node blew up"):
        log_node_boundaries("coder", failing_node)(sample_state)
