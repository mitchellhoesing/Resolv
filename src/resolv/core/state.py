"""Strongly-typed Pydantic V2 Blackboard state for the LangGraph pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

TestStatus = Literal["PENDING", "PASSED", "FAILED"]


class IssueRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    owner: str
    repo: str
    number: int
    title: str
    body: str = ""
    labels: tuple[str, ...] = ()


class BlackboardState(BaseModel):
    """Mutable orchestrator state passed between LangGraph nodes."""

    issue: IssueRef
    workspace_path: Path
    current_diff: str | None = None
    test_status: TestStatus = "PENDING"
    test_output: str | None = None
