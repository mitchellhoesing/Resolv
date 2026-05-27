"""Unit tests for the Blackboard state model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from resolv.core.state import (
    BlackboardState,
    ContextChunk,
    IssueRef,
    IterationRecord,
)


def test_blackboard_defaults(sample_state: BlackboardState) -> None:
    assert sample_state.qa_status == "PENDING"
    assert sample_state.test_status == "PENDING"
    assert sample_state.iteration == 0
    assert sample_state.pruned_context == []
    assert sample_state.history == []
    assert sample_state.current_diff is None
    assert sample_state.scip_index_path is None


def test_blackboard_round_trip_json(sample_state: BlackboardState) -> None:
    payload = sample_state.model_dump_json()
    restored = BlackboardState.model_validate_json(payload)
    assert restored == sample_state


def test_issue_ref_is_frozen(sample_state: BlackboardState) -> None:
    with pytest.raises(ValidationError):
        sample_state.issue.number = 999  # type: ignore[misc]


def test_context_chunk_is_frozen() -> None:
    chunk = ContextChunk(file_path="src/x.py", symbol="foo", snippet="def foo(): ...")
    with pytest.raises(ValidationError):
        chunk.symbol = "bar"  # type: ignore[misc]


def test_record_iteration_appends_history(sample_state: BlackboardState) -> None:
    sample_state.current_diff = "--- a\n+++ b\n"
    sample_state.qa_status = "APPROVED"
    sample_state.qa_findings = ["lint clean"]
    sample_state.test_status = "PASSED"
    sample_state.test_output = "1 passed"
    sample_state.iteration = 2

    record = sample_state.record_iteration()

    assert isinstance(record, IterationRecord)
    assert record.iteration == 2
    assert record.qa_status == "APPROVED"
    assert record.qa_findings == ("lint clean",)
    assert record.test_status == "PASSED"
    assert sample_state.history == [record]


def test_qa_status_rejects_invalid_literal(sample_issue: IssueRef, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        BlackboardState(
            issue=sample_issue,
            workspace_path=tmp_path,
            qa_status="UNKNOWN",  # type: ignore[arg-type]
        )
