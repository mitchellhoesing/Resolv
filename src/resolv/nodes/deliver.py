"""Deliver node — branches, commits, pushes, and opens the upstream PR.

When ``dry_run`` is true, the node performs no git or GitHub side effects.
It logs the proposed branch, commit message, sandbox test output, and the
would-be diff so operators can validate Resolv's output before granting it
write access (see issue #10).
"""

from __future__ import annotations

from typing import Any, Callable

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
    dry_run: bool = False,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def deliver_node(state: BlackboardState) -> dict[str, Any]:
        branch_name = f"{branch_prefix}{state.issue.number}"
        commit_message = f"fix: resolve issue #{state.issue.number} — {state.issue.title}"
        if dry_run:
            return _dry_run_deliver(state, branch_name, commit_message, base_branch)
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
            f"[deliver] repo={state.issue.owner}/{state.issue.repo} "
            f'branch={branch_name} commit="{commit_message}" '
            f"issue=#{state.issue.number} pr={pr_url}"
        )
        return {"test_output": f"PR opened: {pr_url}"}

    return deliver_node


def _dry_run_deliver(
    state: BlackboardState,
    branch_name: str,
    commit_message: str,
    base_branch: str,
) -> dict[str, Any]:
    """Log the would-be delivery without touching git or GitHub."""
    log_event(
        f"[deliver] dry-run: would push branch {branch_name} for issue "
        f"#{state.issue.number} (skipping git commit, push, and PR open)"
    )
    log_event(
        f"[deliver] dry-run summary: repo={state.issue.owner}/{state.issue.repo} "
        f'branch={branch_name} base={base_branch} commit="{commit_message}" '
        f"issue=#{state.issue.number} test_status={state.test_status}"
    )
    diff_text = state.current_diff or "(no diff captured)"
    log_event("[deliver] dry-run diff that would have been submitted:\n" + diff_text)
    test_output = state.test_output or "(no test output captured)"
    log_event("[deliver] dry-run sandbox test results:\n" + test_output)
    return {"test_output": f"DRY RUN: PR not opened for {branch_name}"}
