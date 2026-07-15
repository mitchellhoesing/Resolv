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


def _read_run_log(tmp_path: Path) -> str:
    return "\n".join(
        log_file.read_text(encoding="utf-8")
        for log_file in (tmp_path / "logs").glob("*.log")
    )


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

    log_contents = _read_run_log(state.workspace_path)
    assert "repo=acme/widgets" in log_contents
    assert "branch=resolv/issue-7" in log_contents
    assert 'commit="fix: resolve issue #7' in log_contents
    assert "issue=#7" in log_contents
    assert "pr=https://github.com/acme/widgets/pull/9" in log_contents


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
    assert "[deliver] error: git operation failed" in _read_run_log(state.workspace_path)


def test_dry_run_skips_git_and_pr_and_logs_diff_and_tests(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    fake_repo_cls = mocker.patch("resolv.nodes.deliver.Repo")
    github = MagicMock()
    state.current_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    state.test_status = "PASSED"
    state.test_output = "5 passed, 0 failed"

    node = make_deliver_node(github_client=github, dry_run=True)
    result = node(state)

    # No git or GitHub side effects.
    fake_repo_cls.assert_not_called()
    github.open_pull_request.assert_not_called()

    assert "DRY RUN" in result["test_output"]
    assert "resolv/issue-7" in result["test_output"]

    log_contents = _read_run_log(state.workspace_path)
    assert "dry-run" in log_contents
    assert "resolv/issue-7" in log_contents
    assert "+new" in log_contents  # diff echoed
    assert "5 passed, 0 failed" in log_contents  # sandbox test results echoed
    assert "test_status=PASSED" in log_contents


def test_dry_run_handles_missing_diff_and_test_output(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    fake_repo_cls = mocker.patch("resolv.nodes.deliver.Repo")
    github = MagicMock()
    # state.current_diff / state.test_output default to None.

    node = make_deliver_node(github_client=github, dry_run=True)
    result = node(state)

    fake_repo_cls.assert_not_called()
    github.open_pull_request.assert_not_called()
    assert "DRY RUN" in result["test_output"]

    log_contents = _read_run_log(state.workspace_path)
    assert "(no diff captured)" in log_contents
    assert "(no test output captured)" in log_contents
