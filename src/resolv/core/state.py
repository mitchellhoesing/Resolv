"""Strongly-typed Pydantic V2 Blackboard state for the LangGraph loop."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QAStatus = Literal["PENDING", "APPROVED", "REJECTED"]
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


class IterationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    iteration: int
    diff: str | None
    qa_status: QAStatus
    qa_findings: tuple[str, ...]
    test_status: TestStatus
    test_output: str | None


class BlackboardState(BaseModel):
    """Mutable orchestrator state passed between LangGraph nodes."""

    issue: IssueRef
    workspace_path: Path
    scip_index_path: Path | None = None
    pruned_context: list[ContextChunk] = Field(default_factory=list)
    current_diff: str | None = None
    qa_status: QAStatus = "PENDING"
    qa_findings: list[str] = Field(default_factory=list)
    test_status: TestStatus = "PENDING"
    test_output: str | None = None
    iteration: int = 0
    history: list[IterationRecord] = Field(default_factory=list)

    def record_iteration(self) -> IterationRecord:
        """Snapshot the current loop iteration into the history audit trail."""
        record = IterationRecord(
            iteration=self.iteration,
            diff=self.current_diff,
            qa_status=self.qa_status,
            qa_findings=tuple(self.qa_findings),
            test_status=self.test_status,
            test_output=self.test_output,
        )
        self.history.append(record)
        return record
