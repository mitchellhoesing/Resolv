"""Unit tests for the deliver node."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import GitCommandError
from pytest_mock import MockerFixture

from resolv.core.state import BlackboardState, IssueRef
from resolv.exceptions import DeliveryError
from resolv.nodes.deliver import make_deliver_node


@pytest.fixture
def state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(
        owner="acme", repo="widgets", number=7, title="Crash on empty", body="repro", labels=()
    )
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def test_creates_branch_commits_pushes_and_opens_pr(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    fake_repo_cls = mocker.patch("resolv.nodes.deliver.Repo")
    fake_repo = fake_repo_cls.return_value
    fake_branch = MagicMock()
    fake_repo.create_head.return_value = fake_branch
    fake_origin = MagicMock()
    fake_repo.remote.return_value = fake_origin

    github = MagicMock()
    github.open_pull_request.return_value = "https://github.com/acme/widgets/pull/9"

    node = make_deliver_node(github_client=github, base_branch="main", branch_prefix="resolv/issue-")
    result = node(state)

    fake_repo.create_head.assert_called_once_with("resolv/issue-7")
    fake_branch.checkout.assert_called_once()
    fake_repo.git.add.assert_called_once_with(A=True)
    fake_repo.index.commit.assert_called_once()
    commit_message = fake_repo.index.commit.call_args.args[0]
    assert commit_message.startswith("fix: resolve issue #7")
    fake_origin.push.assert_called_once_with("resolv/issue-7")

    github.open_pull_request.assert_called_once()
    pr_kwargs = github.open_pull_request.call_args.kwargs
    assert pr_kwargs["head_branch"] == "resolv/issue-7"
    assert pr_kwargs["base_branch"] == "main"
    assert "Resolves #7" in pr_kwargs["body"]
    assert "PR opened: https://github.com/acme/widgets/pull/9" in result["test_output"]


def test_wraps_git_failure_in_delivery_error(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    fake_repo_cls = mocker.patch("resolv.nodes.deliver.Repo")
    fake_repo_cls.return_value.create_head.side_effect = GitCommandError(
        "create_head", 128, b"already exists"
    )
    github = MagicMock()
    node = make_deliver_node(github_client=github)
    with pytest.raises(DeliveryError, match="git operation failed"):
        node(state)
    github.open_pull_request.assert_not_called()
