"""Strongly-typed Pydantic V2 Blackboard state for the LangGraph loop."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TestStatus = Literal["PENDING", "PASSED", "FAILED"]


class IssueRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    owner: str
    repo: str
    number: int
    title: str
    body: str = ""
    labels: tuple[str, ...] = ()


class IterationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    iteration: int
    diff: str | None
    test_status: TestStatus
    test_output: str | None


class BlackboardState(BaseModel):
    """Mutable orchestrator state passed between LangGraph nodes."""

    issue: IssueRef
    workspace_path: Path
    current_diff: str | None = None
    test_status: TestStatus = "PENDING"
    test_output: str | None = None
    iteration: int = 0
    history: list[IterationRecord] = Field(default_factory=list)

    def summary(self) -> str:
        """One-line, size-bounded rendering of the state for run logs.

        Reports the *size* of `current_diff` rather than its content: diffs and
        test output are unbounded, and every history record holds another copy
        of both. The full state lives in the checkpointer for inspection.
        """
        diff_bytes = len(self.current_diff) if self.current_diff else 0
        return (
            f"iteration={self.iteration} test_status={self.test_status} "
            f"diff_bytes={diff_bytes} history={len(self.history)}"
        )

    def record_iteration(self) -> IterationRecord:
        """Snapshot the current loop iteration into the history audit trail."""
        record = IterationRecord(
            iteration=self.iteration,
            diff=self.current_diff,
            test_status=self.test_status,
            test_output=self.test_output,
        )
        self.history.append(record)
        return record
