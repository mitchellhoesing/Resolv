"""Unit tests for the Blackboard state model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from resolv.core.state import (
    BlackboardState,
    IssueRef,
    IterationRecord,
)


def test_blackboard_defaults(sample_state: BlackboardState) -> None:
    assert sample_state.test_status == "PENDING"
    assert sample_state.iteration == 0
    assert sample_state.history == []
    assert sample_state.current_diff is None


def test_blackboard_round_trip_json(sample_state: BlackboardState) -> None:
    payload = sample_state.model_dump_json()
    restored = BlackboardState.model_validate_json(payload)
    assert restored == sample_state


def test_issue_ref_is_frozen(sample_state: BlackboardState) -> None:
    with pytest.raises(ValidationError):
        sample_state.issue.number = 999  # type: ignore[misc]


def test_record_iteration_appends_history(sample_state: BlackboardState) -> None:
    sample_state.current_diff = "--- a\n+++ b\n"
    sample_state.test_status = "PASSED"
    sample_state.test_output = "1 passed"
    sample_state.iteration = 2

    record = sample_state.record_iteration()

    assert isinstance(record, IterationRecord)
    assert record.iteration == 2
    assert record.test_status == "PASSED"
    assert sample_state.history == [record]


def test_summary_reports_shape_without_embedding_content(
    sample_state: BlackboardState,
) -> None:
    sample_state.current_diff = "x" * 50_000
    sample_state.test_output = "secret failure detail"
    sample_state.test_status = "FAILED"
    sample_state.iteration = 2
    sample_state.record_iteration()

    summary = sample_state.summary()

    assert summary == (
        "iteration=2 test_status=FAILED diff_bytes=50000 history=1"
    )
    # The unbounded fields must never be inlined into the log line.
    assert "x" * 100 not in summary
    assert "secret failure detail" not in summary


def test_summary_handles_empty_state(sample_state: BlackboardState) -> None:
    assert sample_state.summary() == (
        "iteration=0 test_status=PENDING diff_bytes=0 history=0"
    )


def test_test_status_rejects_invalid_literal(sample_issue: IssueRef, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        BlackboardState(
            issue=sample_issue,
            workspace_path=tmp_path,
            test_status="UNKNOWN",  # type: ignore[arg-type]
        )
