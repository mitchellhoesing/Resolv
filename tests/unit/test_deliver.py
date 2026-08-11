"""Unit tests for the deliver node."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import GitCommandError
from pytest_mock import MockerFixture

from resolv.core.state import BlackboardState, IssueRef
from resolv.exceptions import DeliveryError
from resolv.nodes.deliver import make_deliver_node, make_dry_run_deliver_node


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
    assert "acme/widgets" in log_contents
    assert "resolv/issue-7" in log_contents
    assert (
        "[deliver] opened PR https://github.com/acme/widgets/pull/9 from "
        "resolv/issue-7 into main, resolving issue #7"
    ) in log_contents


def test_warns_in_pr_body_when_diff_touches_tests(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    mocker.patch("resolv.nodes.deliver.Repo")
    state.current_diff = (
        "--- a/src/widgets/parse.py\n"
        "+++ b/src/widgets/parse.py\n"
        "@@ -1 +1 @@\n"
        "--- a/tests/test_parse.py\n"
        "+++ b/tests/test_parse.py\n"
        "@@ -1 +1 @@\n"
    )
    github = MagicMock()

    node = make_deliver_node(github_client=github)
    node(state)

    body = github.open_pull_request.call_args.kwargs["body"]
    assert "[!WARNING]" in body
    assert "> - `tests/test_parse.py`" in body
    assert "src/widgets/parse.py" not in body
    assert "Resolves #7" in body
    assert "[deliver] patch modifies test files: tests/test_parse.py" in _read_run_log(
        state.workspace_path
    )


def test_no_warning_when_diff_touches_source_only(
    mocker: MockerFixture, state: BlackboardState
) -> None:
    mocker.patch("resolv.nodes.deliver.Repo")
    state.current_diff = (
        "--- a/src/widgets/parse.py\n+++ b/src/widgets/parse.py\n@@ -1 +1 @@\n"
    )
    github = MagicMock()

    node = make_deliver_node(github_client=github)
    node(state)

    body = github.open_pull_request.call_args.kwargs["body"]
    assert "[!WARNING]" not in body
    assert body.startswith("Resolves #7")
    assert "patch modifies test files" not in _read_run_log(state.workspace_path)


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


def test_dry_run_deliver_logs_diff_and_test_output_without_opening_pr(
    state: BlackboardState,
) -> None:
    state.current_diff = (
        "diff --git a/src/x.py b/src/x.py\n"
        "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    state.test_output = "4 passed, 0 failed"

    result = make_dry_run_deliver_node()(state)

    assert result["test_output"] == "dry-run: PR not opened for issue #7"
    log_contents = _read_run_log(state.workspace_path)
    # Sentinel that a reviewer can grep the log for.
    assert "dry-run: skipping PR" in log_contents
    # Both artefacts the reviewer needs to validate the run are surfaced.
    assert "+new" in log_contents
    assert "4 passed, 0 failed" in log_contents


def test_dry_run_deliver_warns_when_diff_touches_tests(
    state: BlackboardState,
) -> None:
    """The same red flag a real delivery raises must still fire in a dry run."""
    state.current_diff = (
        "--- a/tests/test_parse.py\n+++ b/tests/test_parse.py\n@@ -1 +1 @@\n"
    )

    make_dry_run_deliver_node()(state)

    log_contents = _read_run_log(state.workspace_path)
    assert (
        "[deliver] dry-run: patch modifies test files: tests/test_parse.py"
        in log_contents
    )


def test_dry_run_deliver_handles_a_run_that_produced_no_diff(
    state: BlackboardState,
) -> None:
    result = make_dry_run_deliver_node()(state)

    assert result["test_output"] == "dry-run: PR not opened for issue #7"
    log_contents = _read_run_log(state.workspace_path)
    assert "no files changed" in log_contents
    assert "dry-run diff: (empty)" in log_contents
