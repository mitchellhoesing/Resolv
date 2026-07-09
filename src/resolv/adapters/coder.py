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
        prior_feedback: str | None,
    ) -> None: ...


def render_user_prompt(issue: IssueRef, prior_feedback: str | None) -> str:
    """Compose the user-facing prompt handed to the Coder backend."""
    sections = [
        f"# Issue #{issue.number}: {issue.title}",
        "",
        issue.body or "(no body provided)",
    ]
    if prior_feedback:
        sections.extend(["", "## Prior attempt feedback", prior_feedback])
    return "\n".join(sections)
