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
