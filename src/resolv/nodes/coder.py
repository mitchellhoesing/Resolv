"""Coder node — resets the workspace, dispatches to the selected backend, captures the diff."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from resolv.adapters.coder import CoderBackend
from resolv.core.state import BlackboardState


def make_coder_node(
    backend: CoderBackend,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def coder_node(state: BlackboardState) -> dict[str, Any]:
        if state.iteration > 0:
            _reset_workspace(state.workspace_path)

        prior_feedback = _compose_feedback(state)
        backend.generate_patch(
            issue=state.issue,
            workspace_path=state.workspace_path,
            prior_feedback=prior_feedback,
        )
        diff = _capture_diff(state.workspace_path)
        return {
            "current_diff": diff,
            "iteration": state.iteration + 1,
            "test_status": "PENDING",
            "test_output": None,
        }

    return coder_node


_DIFF_CAP = 2000


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
