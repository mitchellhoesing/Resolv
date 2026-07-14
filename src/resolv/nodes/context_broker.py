"""Context Broker node — ensures the target repository is present in the workspace.

v2 simplification (deviates from `plan/implementation_plan.md`): snippet
extraction (tree-sitter name matching + git-blame provenance) was removed.
The agentic coder backend explores the workspace itself, so this node's
only job is ingestion: clone the repository on first entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from git import GitCommandError, Repo
from pydantic import SecretStr

from resolv.core.state import BlackboardState
from resolv.exceptions import IngestionError
from resolv.utils.run_log import log_event


def make_context_broker_node(
    *,
    github_token: SecretStr | None = None,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def context_broker_node(state: BlackboardState) -> dict[str, Any]:
        workspace = state.workspace_path
        if not (workspace / ".git").exists():
            log_event(
                f"[context_broker] cloning {state.issue.owner}/{state.issue.repo}"
            )
            _clone(state.issue.owner, state.issue.repo, workspace, github_token)
        else:
            log_event("[context_broker] workspace already present")
        return {}

    return context_broker_node


def _clone(owner: str, repo: str, destination: Path, token: SecretStr | None) -> None:
    base_url = f"github.com/{owner}/{repo}.git"
    url = (
        f"https://{token.get_secret_value()}@{base_url}"
        if token and token.get_secret_value()
        else f"https://{base_url}"
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(url=url, to_path=str(destination))
    except GitCommandError as exc:
        raise IngestionError(f"clone of {owner}/{repo} failed: {exc.stderr or exc}") from exc
