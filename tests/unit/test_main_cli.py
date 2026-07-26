"""Unit tests for the typer CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic import SecretStr
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from resolv.config import Settings
from resolv.core.state import IssueRef, IterationRecord
from resolv.main import app, render_run_summary

runner = CliRunner()


def _history() -> list[IterationRecord]:
    return [
        IterationRecord(
            iteration=1,
            diff="--- a/x\n+++ b/x\n",
            test_status="FAILED",
            test_output="1 failed",
        ),
        IterationRecord(
            iteration=2,
            diff="--- a/y\n+++ b/y\n",
            test_status="PASSED",
            test_output="2 passed",
        ),
    ]


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
        "iteration": 1,
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
    graph.invoke.return_value = {
        "test_status": "FAILED",
        "iteration": 5,
    }
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])
    assert result.exit_code == 1
    assert "did not converge" in result.output


def test_render_run_summary_reports_sizes_by_default() -> None:
    summary = render_run_summary(
        {"test_status": "PASSED", "history": _history()}, verbose=False
    )

    assert summary.splitlines() == [
        "[summary] 2 iteration(s), final status PASSED",
        "  iteration 1: FAILED, diff 16 bytes",
        "  iteration 2: PASSED, diff 16 bytes",
    ]
    # Unbounded content stays out of the default summary.
    assert "1 failed" not in summary
    assert "--- a/x" not in summary


def test_render_run_summary_includes_content_when_verbose() -> None:
    summary = render_run_summary(
        {"test_status": "PASSED", "history": _history()}, verbose=True
    )

    assert "    diff:" in summary
    assert "      --- a/x" in summary
    assert "    test output:" in summary
    assert "      1 failed" in summary


def test_render_run_summary_handles_a_run_with_no_iterations() -> None:
    summary = render_run_summary({"test_status": "FAILED"}, verbose=True)

    assert summary == "[summary] 0 iteration(s), final status FAILED"


def test_cli_prints_run_summary_on_the_stall_path(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = {
        "test_status": "FAILED",
        "iteration": 2,
        "history": _history(),
    }
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])

    assert result.exit_code == 1
    assert "[summary] 2 iteration(s), final status FAILED" in result.output
    assert "  iteration 1: FAILED, diff 16 bytes" in result.output
    assert "did not converge" in result.output


def test_cli_verbose_flag_expands_the_summary(mocker: MockerFixture) -> None:
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
        "iteration": 2,
        "history": _history(),
    }
    mocker.patch("resolv.main.build_production_graph", return_value=graph)

    quiet = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])
    loud = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1", "--verbose"])

    assert quiet.exit_code == 0 and loud.exit_code == 0
    assert "    test output:" not in quiet.output
    assert "    test output:" in loud.output
    assert "      --- a/x" in loud.output


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
