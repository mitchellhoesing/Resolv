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


def _state(workspace: Path, **overrides: object) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="body", labels=())
    base: dict[str, object] = {"issue": issue, "workspace_path": workspace}
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


def test_logs_start(repo: Path) -> None:
    backend = MagicMock()
    node = make_coder_node(backend)
    node(_state(repo))
    assert "[coder] started" in _read_run_log(repo)


def test_logs_what_the_backend_produced_without_the_diff_itself(repo: Path) -> None:
    def write_patch(**kwargs: object) -> None:
        (repo / "f.py").write_text("secret patch body\n", encoding="utf-8")

    backend = MagicMock()
    backend.generate_patch.side_effect = write_patch

    node = make_coder_node(backend)
    node(_state(repo))

    run_log = _read_run_log(repo)
    assert "[coder] wrote +1/-1 lines across 1 file(s)" in run_log
    assert "secret patch body" not in run_log


def test_logs_when_the_backend_changed_nothing(repo: Path) -> None:
    backend = MagicMock()
    node = make_coder_node(backend)
    node(_state(repo))
    assert "[coder] no files changed" in _read_run_log(repo)


def test_backend_error_is_logged_and_reraised(repo: Path) -> None:
    backend = MagicMock()
    backend.generate_patch.side_effect = RuntimeError("backend exploded")
    node = make_coder_node(backend)
    with pytest.raises(RuntimeError, match="backend exploded"):
        node(_state(repo))
    assert "[coder] error: backend exploded" in _read_run_log(repo)
