"""Unit tests for the context broker node (workspace ingestion)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from resolv.core.state import BlackboardState, IssueRef
from resolv.exceptions import IngestionError
from resolv.nodes.context_broker import make_context_broker_node


def _state_for(path: Path) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="fix foo", body="", labels=())
    return BlackboardState(issue=issue, workspace_path=path)


def test_skips_clone_when_workspace_already_cloned(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    fake_clone = mocker.patch("resolv.nodes.context_broker.Repo.clone_from")
    node = make_context_broker_node()
    result = node(_state_for(tmp_path))
    fake_clone.assert_not_called()
    assert result == {}


def test_clone_invoked_when_no_git_present(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    target = tmp_path / "workspace"

    def fake_clone(url: str, to_path: str) -> None:
        Path(to_path).mkdir(parents=True)
        (Path(to_path) / ".git").mkdir()

    fake_repo = mocker.patch(
        "resolv.nodes.context_broker.Repo.clone_from", side_effect=fake_clone
    )
    node = make_context_broker_node()
    result = node(_state_for(target))
    fake_repo.assert_called_once()
    assert result == {}


def test_clone_failure_raises_ingestion_error(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    from git import GitCommandError

    mocker.patch(
        "resolv.nodes.context_broker.Repo.clone_from",
        side_effect=GitCommandError("clone", 128, b"not found"),
    )
    target = tmp_path / "missing"
    node = make_context_broker_node()
    with pytest.raises(IngestionError, match="clone of"):
        node(_state_for(target))
