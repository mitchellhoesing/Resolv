"""Deliver node — branches, commits, pushes, and opens the upstream PR."""

from __future__ import annotations

from collections.abc import Callable
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
        log_event(
            f"[deliver] committing the passing patch to {branch_name} and pushing it "
            f"to {state.issue.owner}/{state.issue.repo}"
        )
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

        try:
            pr_url = github_client.open_pull_request(
                state.issue.owner,
                state.issue.repo,
                head_branch=branch_name,
                base_branch=base_branch,
                title=commit_message,
                body=f"Resolves #{state.issue.number}\n\n{state.issue.body or state.issue.title}",
            )
        except Exception as exc:
            log_event(f"[deliver] error: {exc}")
            raise
        log_event(
            f"[deliver] opened PR {pr_url} from {branch_name} into {base_branch}, "
            f"resolving issue #{state.issue.number}"
        )
        return {"test_output": f"PR opened: {pr_url}"}

    return deliver_node
