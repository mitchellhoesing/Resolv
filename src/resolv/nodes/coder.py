"""Coder node — dispatches to the selected backend and captures the diff."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from resolv.adapters.coder import CoderBackend
from resolv.core.state import BlackboardState
from resolv.utils.diff_stats import describe_diff
from resolv.utils.run_log import log_event


def make_coder_node(
    backend: CoderBackend,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def coder_node(state: BlackboardState) -> dict[str, Any]:
        try:
            backend.generate_patch(
                issue=state.issue,
                workspace_path=state.workspace_path,
            )
        except Exception as exc:
            log_event(f"[coder] error: {exc}")
            raise
        diff = _capture_diff(state.workspace_path)
        log_event(f"[coder] {describe_diff(diff)}")
        return {
            "current_diff": diff,
            "test_status": "PENDING",
            "test_output": None,
        }

    return coder_node


def _capture_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout
