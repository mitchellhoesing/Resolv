"""Deliver node — branches, commits, pushes, and opens the upstream PR."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from git import GitCommandError, Repo

from resolv.adapters.github_client import GitHubClient
from resolv.core.state import BlackboardState
from resolv.exceptions import DeliveryError


def make_deliver_node(
    *,
    github_client: GitHubClient,
    base_branch: str = "main",
    branch_prefix: str = "resolv/issue-",
) -> Callable[[BlackboardState], dict[str, Any]]:
    def deliver_node(state: BlackboardState) -> dict[str, Any]:
        _timestamp = datetime.now(timezone.utc).strftime("%m/%d/%YT%H:%MZ")
        print(f'"timestamp": {_timestamp}')
        print('"node": Deliver')
        print('"event": "Node Activated"')
        branch_name = f"{branch_prefix}{state.issue.number}"
        commit_message = f"fix: resolve issue #{state.issue.number} — {state.issue.title}"
        try:
            repo = Repo(str(state.workspace_path))
            branch = repo.create_head(branch_name)
            branch.checkout()
            repo.git.add(A=True)
            repo.index.commit(commit_message)
            repo.remote("origin").push(branch_name)
        except GitCommandError as exc:
            raise DeliveryError(
                f"git operation failed for {branch_name}: {exc.stderr or exc}"
            ) from exc

        pr_url = github_client.open_pull_request(
            state.issue.owner,
            state.issue.repo,
            head_branch=branch_name,
            base_branch=base_branch,
            title=commit_message,
            body=f"Resolves #{state.issue.number}\n\n{state.issue.body or state.issue.title}",
        )
        return {"test_output": f"PR opened: {pr_url}"}

    return deliver_node
