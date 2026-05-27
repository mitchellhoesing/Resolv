"""Coder node — invokes the selected Coder backend.

Phase 2 stub: bumps iteration and writes a placeholder diff. Real
backend dispatch lands in Phase 4.
"""

from __future__ import annotations

from typing import Any

from resolv.core.state import BlackboardState


def coder_node(state: BlackboardState) -> dict[str, Any]:
    return {
        "current_diff": "--- a/stub\n+++ b/stub\n",
        "iteration": state.iteration + 1,
        "qa_status": "PENDING",
        "qa_findings": [],
        "test_status": "PENDING",
        "test_output": None,
    }
