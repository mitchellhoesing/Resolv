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


def test_blackboard_rejects_an_unknown_test_status(
    sample_state: BlackboardState,
) -> None:
    with pytest.raises(ValidationError):
        BlackboardState(
            issue=sample_state.issue,
            workspace_path=sample_state.workspace_path,
            test_status="MAYBE",  # type: ignore[arg-type]
        )


def test_test_status_rejects_invalid_literal(sample_issue: IssueRef, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        BlackboardState(
            issue=sample_issue,
            workspace_path=tmp_path,
            test_status="UNKNOWN",  # type: ignore[arg-type]
        )
