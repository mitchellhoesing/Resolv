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
            pruned_context=state.pruned_context,
            prior_feedback=prior_feedback,
        )
        diff = _capture_diff(state.workspace_path)
        return {
            "current_diff": diff,
            "iteration": state.iteration + 1,
            "qa_status": "PENDING",
            "qa_findings": [],
            "test_status": "PENDING",
            "test_output": None,
        }

    return coder_node


def _compose_feedback(state: BlackboardState) -> str | None:
    if state.iteration == 0:
        return None
    parts: list[str] = []
    if state.qa_findings:
        parts.append("QA findings:\n" + "\n".join(state.qa_findings))
    if state.test_status == "FAILED" and state.test_output:
        parts.append("Test output:\n" + state.test_output)
    return "\n\n".join(parts) if parts else None


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
