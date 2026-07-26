"""Unit tests for graph-module concerns that are not about topology.

The compiled graph's checkpointer must round-trip the Blackboard's own types as
themselves. LangGraph's default serializer allows *any* importable type with a
warning; under its future default, unregistered types silently come back as
plain dicts. `_CHECKPOINT_SERDE` pins an explicit allowlist instead.
"""

from __future__ import annotations

from pydantic import BaseModel

from resolv.core.graph import _CHECKPOINT_SERDE
from resolv.core.state import IssueRef, IterationRecord


class _UnregisteredModel(BaseModel):
    """Stands in for a type nobody added to the checkpoint allowlist."""

    value: str


def test_checkpoint_serde_round_trips_blackboard_types() -> None:
    issue = IssueRef(
        owner="acme", repo="widgets", number=1, title="t", body="", labels=("bug",)
    )
    record = IterationRecord(
        iteration=1, diff="--- a\n+++ b\n", test_status="FAILED", test_output="boom"
    )

    for original in (issue, record):
        restored = _CHECKPOINT_SERDE.loads_typed(_CHECKPOINT_SERDE.dumps_typed(original))
        assert type(restored) is type(original)
        assert restored == original


def test_checkpoint_serde_allowlist_is_explicit_not_permissive() -> None:
    """A type outside the allowlist must not be reconstructed.

    This is the regression guard: on LangGraph's permissive default the
    unregistered model would round-trip intact, so this test fails if the
    explicit allowlist is ever dropped.
    """
    unregistered = _UnregisteredModel(value="x")

    restored = _CHECKPOINT_SERDE.loads_typed(_CHECKPOINT_SERDE.dumps_typed(unregistered))

    assert not isinstance(restored, _UnregisteredModel)
