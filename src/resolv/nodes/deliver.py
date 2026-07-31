"""Deliver node — branches, commits, pushes, and opens the upstream PR."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from git import GitCommandError, Repo

from resolv.adapters.github_client import GitHubClient
from resolv.core.state import BlackboardState
from resolv.exceptions import DeliveryError
from resolv.utils.run_log import log_event


def make_deliver_node(
    *,
    github_client: GitHubClient,
    base_branch: str = "main",
    branch_prefix: str = "resolv/issue-",
) -> Callable[[BlackboardState], dict[str, Any]]:
    def deliver_node(state: BlackboardState) -> dict[str, Any]:
        branch_name = f"{branch_prefix}{state.issue.number}"
        commit_message = f"fix: resolve issue #{state.issue.number} — {state.issue.title}"
        log_event(f"[deliver] pushing branch {branch_name} for issue #{state.issue.number}")
        try:
            repo = Repo(str(state.workspace_path))
            branch = repo.create_head(branch_name)
            branch.checkout()
            repo.git.add(A=True)
            repo.index.commit(commit_message)
            repo.remote("origin").push(branch_name)
        except GitCommandError as exc:
            log_event(
                f"[deliver] error: git operation failed for {branch_name}: {exc.stderr or exc}"
            )
            raise DeliveryError(
                f"git operation failed for {branch_name}: {exc.stderr or exc}"
            ) from exc

        body = f"Resolves #{state.issue.number}\n\n{state.issue.body or state.issue.title}"
        edited_tests = _edited_test_paths(state.current_diff)
        if edited_tests:
            log_event(f"[deliver] patch modifies test files: {', '.join(edited_tests)}")
            body = _test_edit_warning(edited_tests) + body
        try:
            pr_url = github_client.open_pull_request(
                state.issue.owner,
                state.issue.repo,
                head_branch=branch_name,
                base_branch=base_branch,
                title=commit_message,
                body=body,
            )
        except Exception as exc:
            log_event(f"[deliver] error: {exc}")
            raise
        log_event(
            f"[deliver] repo={state.issue.owner}/{state.issue.repo} "
            f'branch={branch_name} commit="{commit_message}" '
            f"issue=#{state.issue.number} pr={pr_url}"
        )
        return {"test_output": f"PR opened: {pr_url}"}

    return deliver_node


# The coder agent runs the suite itself, so "make the tests pass" is reachable by
# weakening them. The authoritative re-run cannot catch that — it executes
# against the agent's workspace, test edits included — so surface it to the
# reviewer rather than block: a fix sometimes legitimately updates a test.
_DIFF_TARGET_PATH = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def _edited_test_paths(diff: str | None) -> list[str]:
    """List the test files the diff touches, in the order they appear."""
    if not diff:
        return []
    return [path for path in _DIFF_TARGET_PATH.findall(diff) if _is_test_path(path)]


def _is_test_path(path: str) -> bool:
    target = PurePosixPath(path)
    if "tests" in target.parts:
        return True
    if target.suffix != ".py":
        return False
    return (
        target.name == "conftest.py"
        or target.name.startswith("test_")
        or target.name.endswith("_test.py")
    )


def _test_edit_warning(paths: list[str]) -> str:
    listed = "\n".join(f"> - `{path}`" for path in paths)
    return (
        "> [!WARNING]\n"
        "> **This patch modifies test files.** Confirm the fix is in the source "
        "rather than in the suite.\n"
        f"{listed}\n\n"
    )
