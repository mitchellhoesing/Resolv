"""Unit tests for the PyGithub adapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.adapters.github_client import GitHubClient
from resolv.exceptions import DeliveryError, IngestionError


@pytest.fixture
def fake_github(mocker: MockerFixture) -> MagicMock:
    fake = mocker.patch("resolv.adapters.github_client.Github", autospec=True)
    mocker.patch("resolv.adapters.github_client.Auth", autospec=True)
    return fake


def test_empty_token_raises_ingestion_error() -> None:
    with pytest.raises(IngestionError):
        GitHubClient(SecretStr(""))


def test_fetch_issue_returns_issue_ref(fake_github: MagicMock) -> None:
    label = MagicMock()
    label.name = "bug"
    issue = MagicMock(title="Crash", body="repro", labels=[label])
    repo = MagicMock()
    repo.get_issue.return_value = issue
    fake_github.return_value.get_repo.return_value = repo

    client = GitHubClient(SecretStr("ghp_x"))
    result = client.fetch_issue("acme", "widgets", 42)

    fake_github.return_value.get_repo.assert_called_once_with("acme/widgets")
    repo.get_issue.assert_called_once_with(42)
    assert result.owner == "acme"
    assert result.repo == "widgets"
    assert result.number == 42
    assert result.title == "Crash"
    assert result.body == "repro"
    assert result.labels == ("bug",)


def test_fetch_issue_wraps_api_errors(fake_github: MagicMock) -> None:
    fake_github.return_value.get_repo.side_effect = RuntimeError("404")
    client = GitHubClient(SecretStr("ghp_x"))
    with pytest.raises(IngestionError, match="404"):
        client.fetch_issue("acme", "widgets", 1)


def test_open_pull_request_returns_html_url(fake_github: MagicMock) -> None:
    pr = MagicMock(html_url="https://github.com/acme/widgets/pull/7")
    repo = MagicMock()
    repo.create_pull.return_value = pr
    fake_github.return_value.get_repo.return_value = repo

    client = GitHubClient(SecretStr("ghp_x"))
    url = client.open_pull_request("acme", "widgets", "resolv/issue-1", "main", "fix", "body")

    repo.create_pull.assert_called_once_with(
        title="fix", body="body", head="resolv/issue-1", base="main"
    )
    assert url == "https://github.com/acme/widgets/pull/7"


def test_open_pull_request_wraps_api_errors(fake_github: MagicMock) -> None:
    repo = MagicMock()
    repo.create_pull.side_effect = RuntimeError("422")
    fake_github.return_value.get_repo.return_value = repo

    client = GitHubClient(SecretStr("ghp_x"))
    with pytest.raises(DeliveryError, match="422"):
        client.open_pull_request("acme", "widgets", "h", "main", "t", "b")
