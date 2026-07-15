"""Unit tests for the typer CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic import SecretStr
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from resolv.config import Settings
from resolv.core.state import IssueRef
from resolv.main import app

runner = CliRunner()


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
    dispatch_mock.assert_called_once_with(settings, "acme", "widgets", 7, dry_run=False)


def test_cli_dispatch_propagates_container_failure(mocker: MockerFixture) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    mocker.patch("resolv.main.dispatch_issue", return_value=17)

    result = runner.invoke(app, ["dispatch", "--repo", "acme/widgets", "--issue", "7"])

    assert result.exit_code == 17


def test_cli_run_dry_run_forwards_flag_to_production_graph(
    mocker: MockerFixture,
) -> None:
    mocker.patch("resolv.main.get_settings", return_value=_stub_settings())
    github = MagicMock()
    github.fetch_issue.return_value = IssueRef(
        owner="a", repo="b", number=1, title="t", body="", labels=()
    )
    mocker.patch("resolv.main.GitHubClient", return_value=github)
    graph = MagicMock()
    graph.invoke.return_value = {
        "test_status": "PASSED",
        "test_output": "DRY RUN: PR not opened for resolv/issue-1",
        "iteration": 1,
    }
    build_graph_mock = mocker.patch(
        "resolv.main.build_production_graph", return_value=graph
    )

    result = runner.invoke(
        app, ["run", "--repo", "a/b", "--issue", "1", "--dry-run"]
    )

    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert build_graph_mock.call_args.kwargs["dry_run"] is True


def test_cli_run_defaults_dry_run_off(mocker: MockerFixture) -> None:
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
    build_graph_mock = mocker.patch(
        "resolv.main.build_production_graph", return_value=graph
    )

    result = runner.invoke(app, ["run", "--repo", "a/b", "--issue", "1"])

    assert result.exit_code == 0
    assert build_graph_mock.call_args.kwargs["dry_run"] is False


def test_cli_dispatch_forwards_dry_run(mocker: MockerFixture) -> None:
    settings = _stub_settings()
    mocker.patch("resolv.main.get_settings", return_value=settings)
    dispatch_mock = mocker.patch("resolv.main.dispatch_issue", return_value=0)

    result = runner.invoke(
        app,
        ["dispatch", "--repo", "acme/widgets", "--issue", "7", "--dry-run"],
    )

    assert result.exit_code == 0
    dispatch_mock.assert_called_once_with(
        settings, "acme", "widgets", 7, dry_run=True
    )
