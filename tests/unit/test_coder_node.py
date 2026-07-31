"""Unit tests for the coder node (orchestration around the backend)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.nodes.coder import make_coder_node


def _read_run_log(tmp_path: Path) -> str:
    return "\n".join(
        log_file.read_text(encoding="utf-8")
        for log_file in (tmp_path / "logs").glob("*.log")
    )


def _state(workspace: Path, *, iteration: int = 0, **overrides: object) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="body", labels=())
    base: dict[str, object] = {
        "issue": issue,
        "workspace_path": workspace,
        "iteration": iteration,
    }
    base.update(overrides)
    return BlackboardState(**base)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(path), check=True)
    (path / "f.py").write_text("a = 1\n")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(path), check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def test_dispatches_to_backend_and_captures_diff(repo: Path) -> None:
    def backend_writes_change(**kwargs: object) -> None:
        (repo / "f.py").write_text("a = 2\n")

    backend = MagicMock()
    backend.generate_patch.side_effect = backend_writes_change

    node = make_coder_node(backend)
    result = node(_state(repo))

    assert result["iteration"] == 1
    assert "-a = 1" in result["current_diff"]
    assert "+a = 2" in result["current_diff"]
    assert result["test_status"] == "PENDING"
    backend.generate_patch.assert_called_once_with(
        issue=_state(repo).issue, workspace_path=repo
    )


def test_leaves_the_workspace_alone_before_dispatching(repo: Path) -> None:
    """The node must not reset: there is no prior attempt to discard."""
    (repo / "stray.txt").write_text("uncommitted")
    observed: dict[str, object] = {}

    def capture(**kwargs: object) -> None:
        observed["stray_exists"] = (repo / "stray.txt").exists()

    backend = MagicMock()
    backend.generate_patch.side_effect = capture

    node = make_coder_node(backend)
    node(_state(repo))

    assert observed["stray_exists"] is True


def test_logs_iteration_start(repo: Path) -> None:
    backend = MagicMock()
    node = make_coder_node(backend)
    node(_state(repo))
    assert "[coder] iteration 1 started" in _read_run_log(repo)


def test_backend_error_is_logged_and_reraised(repo: Path) -> None:
    backend = MagicMock()
    backend.generate_patch.side_effect = RuntimeError("backend exploded")
    node = make_coder_node(backend)
    with pytest.raises(RuntimeError, match="backend exploded"):
        node(_state(repo))
    assert "[coder] error: backend exploded" in _read_run_log(repo)
