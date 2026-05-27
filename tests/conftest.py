"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from resolv.core.state import BlackboardState, IssueRef


@pytest.fixture
def sample_issue() -> IssueRef:
    return IssueRef(
        owner="acme",
        repo="widgets",
        number=42,
        title="Crash on empty input",
        body="Reproduces by calling process('')",
        labels=("bug",),
    )


@pytest.fixture
def sample_state(sample_issue: IssueRef, tmp_path: Path) -> BlackboardState:
    return BlackboardState(issue=sample_issue, workspace_path=tmp_path)
