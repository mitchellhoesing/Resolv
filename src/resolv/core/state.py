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


class ContextChunk(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_path: str
    symbol: str
    snippet: str
    provenance: tuple[str, ...] = ()  # git-blame lines: commits that last touched this snippet


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
    scip_index_path: Path | None = None
    pruned_context: list[ContextChunk] = Field(default_factory=list)
    current_diff: str | None = None
    test_status: TestStatus = "PENDING"
    test_output: str | None = None
    iteration: int = 0
    history: list[IterationRecord] = Field(default_factory=list)

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
