"""Coder backend Protocol and shared prompt rendering.

A Coder backend takes an issue + workspace and mutates the workspace in
place to apply a proposed fix. The orchestrator captures the resulting
diff after the call returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from resolv.core.state import IssueRef


@runtime_checkable
class CoderBackend(Protocol):
    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
    ) -> None: ...


def render_user_prompt(issue: IssueRef) -> str:
    """Compose the user-facing prompt handed to the Coder backend."""
    return "\n".join(
        [
            f"# Issue #{issue.number}: {issue.title}",
            "",
            issue.body or "(no body provided)",
        ]
    )
