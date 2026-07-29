"""Coder node — resets the workspace, dispatches to the selected backend, captures the diff."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from resolv.adapters.coder import CoderBackend
from resolv.core.state import BlackboardState
from resolv.utils.run_log import log_event


def make_coder_node(
    backend: CoderBackend,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def coder_node(state: BlackboardState) -> dict[str, Any]:
        attempt = state.iteration + 1
        if state.iteration > 0:
            log_event(
                f"[coder] iteration {attempt}: discarding the workspace changes from "
                f"iteration {state.iteration} and retrying with its test failures as feedback"
            )
            _reset_workspace(state.workspace_path)
        else:
            log_event(f"[coder] iteration {attempt}: first attempt at issue #{state.issue.number}")

        prior_feedback = _compose_feedback(state)
        try:
            backend.generate_patch(
                issue=state.issue,
                workspace_path=state.workspace_path,
                prior_feedback=prior_feedback,
            )
        except Exception as exc:
            log_event(f"[coder] error: {exc}")
            raise
        diff = _capture_diff(state.workspace_path)
        log_event(f"[coder] iteration {attempt}: {_describe_diff(diff)}")
        return {
            "current_diff": diff,
            "iteration": attempt,
            "test_status": "PENDING",
            "test_output": None,
        }

    return coder_node


_DIFF_CAP = 2000


def _describe_diff(diff: str) -> str:
    """Size and file count of what the backend left in the workspace, for the run log.

    The diff's content stays out of the log — it is unbounded, and `--verbose`
    on the run summary is the opt-in for seeing it.
    """
    if not diff:
        return "the backend left the workspace unchanged"
    changed_file_count = sum(
        1 for line in diff.splitlines() if line.startswith("diff --git ")
    )
    return f"wrote a {len(diff)}-byte diff across {changed_file_count} file(s)"


def _compose_feedback(state: BlackboardState) -> str | None:
    if not state.history:
        return None
    header = (
        "These are your previous attempts to fix this issue, in order. Each was "
        "applied to the workspace and did NOT resolve it — review what was changed "
        "and why it failed, and do not repeat the same approach."
    )
    blocks: list[str] = []
    for record in state.history:
        lines = [f"### Attempt {record.iteration} — tests {record.test_status}"]
        if record.diff:
            lines.append("Diff that was tried:\n```diff\n" + record.diff[:_DIFF_CAP] + "\n```")
        if record.test_status == "FAILED" and record.test_output:
            lines.append("Test output:\n" + record.test_output)
        blocks.append("\n".join(lines))
    return header + "\n\n" + "\n\n".join(blocks)


def _reset_workspace(workspace: Path) -> None:
    subprocess.run(
        ["git", "reset", "--hard"], cwd=str(workspace), capture_output=True, check=False
    )
    subprocess.run(
        ["git", "clean", "-fdx"], cwd=str(workspace), capture_output=True, check=False
    )


def _capture_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout
