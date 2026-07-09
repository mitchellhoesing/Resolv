"""Coder backend Protocol and shared prompt rendering.

A Coder backend takes an issue + workspace and mutates the workspace in
place to apply a proposed fix. The orchestrator captures the resulting
diff after the call returns.
"""

from __future__ import annotations

from datetime import datetime, timezone
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


_PROMPT_LOG_DIRECTORY = Path("logs")


def dump_prompt_log(prompt: str) -> None:
    """Append the fully rendered coder prompt to a per-minute UTC log file.

    Windows forbids ':' in file names, so the time separator is '-'
    (DD-MM-YYYYTHH-MMZ). Prompts rendered within the same minute are
    appended to the same file, separated by a delimiter line.
    """
    _PROMPT_LOG_DIRECTORY.mkdir(exist_ok=True)
    log_file_name = datetime.now(timezone.utc).strftime("%d-%m-%YT%H-%MZ") + ".log"
    with (_PROMPT_LOG_DIRECTORY / log_file_name).open("a", encoding="utf-8") as log_file:
        log_file.write(prompt + "\n\n" + "=" * 80 + "\n\n")


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
