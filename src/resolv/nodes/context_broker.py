"""Context Broker node — clones the target repo and extracts code chunks relevant to the issue.

v1 simplification (deviates from `plan/implementation_plan.md`): SCIP indexing is deferred.
The broker walks the workspace's Python files, parses each with tree-sitter, and emits
top-level function/class snippets whose names appear in the issue text. Falls back to
the first N definitions when no name matches. Cross-file symbol resolution via SCIP
remains a follow-up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from git import GitCommandError, Repo
from pydantic import SecretStr

from resolv.core.state import BlackboardState, ContextChunk
from resolv.exceptions import IngestionError
from resolv.utils.ast_tools import extract_definitions

_SNIPPET_CAP = 2000


def make_context_broker_node(
    *,
    max_chunks: int,
    github_token: SecretStr | None = None,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def context_broker_node(state: BlackboardState) -> dict[str, Any]:
        workspace = state.workspace_path
        if not (workspace / ".git").exists():
            _clone(state.issue.owner, state.issue.repo, workspace, github_token)

        haystack = f"{state.issue.title}\n{state.issue.body}".lower()
        matched: list[ContextChunk] = []
        fallback: list[ContextChunk] = []

        for py_file in workspace.rglob("*.py"):
            if ".git" in py_file.parts or "venv" in py_file.parts:
                continue
            try:
                source = py_file.read_bytes()
            except OSError:
                continue
            relative = py_file.relative_to(workspace).as_posix()
            for name, snippet in extract_definitions(source):
                chunk = ContextChunk(
                    file_path=relative,
                    symbol=name,
                    snippet=snippet[:_SNIPPET_CAP],
                )
                if name.lower() in haystack:
                    matched.append(chunk)
                    if len(matched) >= max_chunks:
                        return {"pruned_context": matched, "scip_index_path": None}
                elif len(fallback) < max_chunks:
                    fallback.append(chunk)

        selected = matched or fallback[:max_chunks]
        return {"pruned_context": selected, "scip_index_path": None}

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
