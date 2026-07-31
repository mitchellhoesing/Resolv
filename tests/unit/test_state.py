"""Unit tests for the Blackboard state model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from resolv.core.state import BlackboardState, IssueRef


def test_blackboard_defaults(sample_state: BlackboardState) -> None:
    assert sample_state.test_status == "PENDING"
    assert sample_state.current_diff is None
    assert sample_state.test_output is None


def test_blackboard_round_trip_json(sample_state: BlackboardState) -> None:
    payload = sample_state.model_dump_json()
    restored = BlackboardState.model_validate_json(payload)
    assert restored == sample_state


def test_issue_ref_is_frozen(sample_state: BlackboardState) -> None:
    with pytest.raises(ValidationError):
        sample_state.issue.number = 999  # type: ignore[misc]


def test_summary_reports_shape_without_embedding_content(
    sample_state: BlackboardState,
) -> None:
    sample_state.current_diff = "x" * 50_000
    sample_state.test_output = "secret failure detail"
    sample_state.test_status = "FAILED"

    summary = sample_state.summary()

    assert summary == "test_status=FAILED diff_bytes=50000"
    # The unbounded fields must never be inlined into the log line.
    assert "x" * 100 not in summary
    assert "secret failure detail" not in summary


def test_summary_handles_empty_state(sample_state: BlackboardState) -> None:
    assert sample_state.summary() == "test_status=PENDING diff_bytes=0"


def test_test_status_rejects_invalid_literal(sample_issue: IssueRef, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        BlackboardState(
            issue=sample_issue,
            workspace_path=tmp_path,
            test_status="UNKNOWN",  # type: ignore[arg-type]
        )
