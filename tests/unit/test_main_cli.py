"""Unit tests for the typer CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pydantic import SecretStr
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from resolv.config import Settings
from resolv.core.graph import build_graph, sqlite_checkpointer
from resolv.core.state import BlackboardState, IssueRef
from resolv.main import app, render_run_summary, render_state_history

runner = CliRunner()


def _finished_run(status: str = "PASSED") -> dict[str, object]:
    return {
        "test_status": status,
        "test_output": "1 failed",
        "current_diff": "--- a/x\n+++ b/x\n",
    }


def _stub_settings() -> Settings:
    return Settings(github_token=SecretStr("ghp_fake"))


def test_cli_rejects_bad_repo_format() -> None:
    result = runner.invoke(app, ["run", "--repo", "no-slash", "--issue", "1"])
    assert result.exit_code == 2
    assert "owner/name" in result.output


def test_cli_success_path_reports_pr_url(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = {
        "test_status": "PASSED",
        "test_output": "PR opened: https://github.com/a/b/pull/9",
    }
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])
    assert result.exit_code == 0
    assert "PR opened" in result.output


def test_cli_stall_path_exits_nonzero(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = {"test_status": "FAILED"}
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])
    assert result.exit_code == 1
    assert "Coder agent did not reach a passing suite" in result.output


def test_render_run_summary_reports_sizes_by_default() -> None:
    summary = render_run_summary(_finished_run(), verbose=False)

    assert summary == "[summary] final status PASSED, diff 16 bytes"
    # Unbounded content stays out of the default summary.
    assert "1 failed" not in summary
    assert "--- a/x" not in summary


def test_render_run_summary_includes_content_when_verbose() -> None:
    summary = render_run_summary(_finished_run(), verbose=True)

    assert "    diff:" in summary
    assert "      --- a/x" in summary
    assert "    test output:" in summary
    assert "      1 failed" in summary


def test_render_run_summary_handles_a_run_that_produced_nothing() -> None:
    summary = render_run_summary({"test_status": "FAILED"}, verbose=True)

    assert summary == "[summary] final status FAILED, diff 0 bytes"


def test_cli_prints_run_summary_on_the_stall_path(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = _finished_run("FAILED")
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])

    assert result.exit_code == 1
    assert "[summary] final status FAILED, diff 16 bytes" in result.output
    assert "Coder agent did not reach a passing suite" in result.output


def test_cli_verbose_flag_expands_the_summary(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = _finished_run()
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    quiet = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])
    loud = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1", "--verbose"])

    assert quiet.exit_code == 0 and loud.exit_code == 0
    assert "    test output:" not in quiet.output
    assert "    test output:" in loud.output
    assert "      --- a/x" in loud.output


def _write_checkpoint_database(destination: Path) -> None:
    """Run a stub graph against a real database so `inspect` has something to read."""
    from tests.integration._stub_nodes import (
        stub_coder,
        stub_context_broker,
        stub_deliver,
        stub_env_installer,
        stub_test_runner,
    )

    graph = build_graph(
        context_broker_fn=stub_context_broker,
        env_installer_fn=stub_env_installer,
        coder_fn=stub_coder,
        test_runner_fn=stub_test_runner,
        deliver_fn=stub_deliver,
        checkpointer=sqlite_checkpointer(destination),
    )
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    graph.invoke(
        BlackboardState(issue=issue, workspace_path=destination.parent),
        config={"configurable": {"thread_id": "a/b#1"}},
    )


def test_cli_inspect_prints_the_state_history(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    _write_checkpoint_database(database)

    result = runner.invoke(
        app,
        ["inspect", "--repo", "a/b", "--issue", "1", "--database", str(database)],
    )

    assert result.exit_code == 0
    assert "[history]" in result.output
    # The executed path, including nodes the final state alone would not reveal.
    for node_name in ("context_broker", "env_installer", "coder", "test_runner"):
        assert f"before {node_name}" in result.output


def test_cli_inspect_reports_a_missing_database(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "inspect",
            "--repo", "a/b",
            "--issue", "1",
            "--database", str(tmp_path / "absent.sqlite"),
        ],
    )

    assert result.exit_code == 1
    assert "no checkpoint database" in result.output


def test_cli_inspect_without_a_database_names_both_paths_it_tried() -> None:
    result = runner.invoke(app, ["inspect", "--repo", "a/b", "--issue", "1"])

    assert result.exit_code == 1
    assert "a__b__issue-1" in result.output
    assert "checkpoints.sqlite" in result.output


def test_render_state_history_handles_an_empty_database() -> None:
    assert render_state_history([]) == "[history] no checkpoints recorded"


def test_cli_dispatch_rejects_bad_repo_format() -> None:
    result = runner.invoke(app, ["dispatch", "--repo", "no-slash", "--issue", "1"])
    assert result.exit_code == 2
    assert "owner/name" in result.output


def test_cli_dispatch_launches_container_and_mirrors_exit_code(
    mocker: MockerFixture,
) -> None:
    settings = _stub_settings()
    mocker.patch("resolv.main.get_settings", return_value=settings)
    dispatch_mock = mocker.patch("resolv.main.dispatch_issue", return_value=0)

    result = runner.invoke(app, ["dispatch", "--repo", "acme/widgets", "--issue", "7"])

    assert result.exit_code == 0
    dispatch_mock.assert_called_once_with(settings, "acme", "widgets", 7)


def test_cli_dispatch_propagates_container_failure(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    mocker.patch("resolv.main.dispatch_issue", return_value=17)

    result = runner.invoke(app, ["dispatch", "--repo", "acme/widgets", "--issue", "7"])

    assert result.exit_code == 17
