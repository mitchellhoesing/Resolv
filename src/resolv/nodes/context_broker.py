"""Context Broker node — clones the target repo and extracts code chunks relevant to the issue.

v1 simplification (deviates from `plan/implementation_plan.md`): SCIP indexing is deferred.
The broker walks the workspace's Python files, parses each with tree-sitter, and emits
top-level function/class snippets whose names appear in the issue text. When no name
matches it emits nothing, leaving retrieval to the coder backend rather than guessing.
Cross-file symbol resolution via SCIP remains a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from git import GitCommandError, Repo
from pydantic import SecretStr

from resolv.core.state import BlackboardState, ContextChunk
from resolv.exceptions import IngestionError
from resolv.utils.ast_tools import extract_definitions
from resolv.utils.git_provenance import blame_provenance

_SNIPPET_CAP = 2000

# Path components that mark version-control internals or vendored dependencies.
# Any *.py file whose path passes through one of these directories is skipped so
# the broker only parses the project's own first-party source. The venv names
# cover the common naming conventions; "site-packages" catches an environment
# regardless of how its top-level directory was named.
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        "venv",
        ".venv",
        "env",
        ".env",
        "virtualenv",
        ".virtualenv",
        ".tox",
        "site-packages",
    }
)


@dataclass(frozen=True)
class _Candidate:
    """A chunk selected for context, plus the line span needed to blame it."""

    chunk: ContextChunk
    start_line: int
    end_line: int


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
        matched: list[_Candidate] = []

        for py_file in workspace.rglob("*.py"):
            if _EXCLUDED_DIRS.intersection(py_file.parts):
                continue
            try:
                source = py_file.read_bytes()
            except OSError:
                continue
            relative = py_file.relative_to(workspace).as_posix()
            for definition in extract_definitions(source):
                if definition.name.lower() not in haystack:
                    continue
                matched.append(
                    _Candidate(
                        chunk=ContextChunk(
                            file_path=relative,
                            symbol=definition.name,
                            snippet=definition.snippet[:_SNIPPET_CAP],
                        ),
                        start_line=definition.start_line,
                        end_line=definition.end_line,
                    )
                )
                if len(matched) >= max_chunks:
                    return _finalize(workspace, matched)

        return _finalize(workspace, matched)

    return context_broker_node


def _finalize(workspace: Path, candidates: list[_Candidate]) -> dict[str, Any]:
    """Attach git-blame provenance to each surfaced chunk and package the result."""
    chunks = [
        candidate.chunk.model_copy(
            update={
                "provenance": blame_provenance(
                    str(workspace),
                    candidate.chunk.file_path,
                    candidate.start_line,
                    candidate.end_line,
                )
            }
        )
        for candidate in candidates
    ]
    return {"pruned_context": chunks, "scip_index_path": None}


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
