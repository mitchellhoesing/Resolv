"""Unit tests for the coder node (orchestration around the backend)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.nodes.coder import make_coder_node


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


def test_first_iteration_skips_reset_and_captures_diff(repo: Path) -> None:
    def backend_writes_change(**kwargs: object) -> None:
        (repo / "f.py").write_text("a = 2\n")

    backend = MagicMock()
    backend.generate_patch.side_effect = backend_writes_change

    node = make_coder_node(backend)
    result = node(_state(repo))

    assert result["iteration"] == 1
    assert "-a = 1" in result["current_diff"]
    assert "+a = 2" in result["current_diff"]
    assert result["qa_status"] == "PENDING"
    assert result["test_status"] == "PENDING"
    backend.generate_patch.assert_called_once()
    kwargs = backend.generate_patch.call_args.kwargs
    assert kwargs["prior_feedback"] is None


def test_subsequent_iteration_resets_workspace_and_passes_feedback(repo: Path) -> None:
    (repo / "stray.txt").write_text("uncommitted")
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> None:
        captured.update(kwargs)
        captured["stray_exists"] = (repo / "stray.txt").exists()
        (repo / "f.py").write_text("a = 3\n")

    backend = MagicMock()
    backend.generate_patch.side_effect = capture

    state = _state(
        repo,
        iteration=1,
        qa_findings=["missing docstring", "long line"],
        test_status="FAILED",
        test_output="3 failed",
    )
    node = make_coder_node(backend)
    result = node(state)

    assert captured["stray_exists"] is False  # workspace was cleaned
    feedback = captured["prior_feedback"]
    assert isinstance(feedback, str)
    assert "missing docstring" in feedback
    assert "3 failed" in feedback
    assert result["iteration"] == 2
    assert "+a = 3" in result["current_diff"]


def test_iteration_without_feedback_passes_none(repo: Path) -> None:
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> None:
        captured.update(kwargs)

    backend = MagicMock()
    backend.generate_patch.side_effect = capture

    node = make_coder_node(backend)
    node(_state(repo, iteration=1, qa_findings=[], test_status="PASSED", test_output=None))
    assert captured["prior_feedback"] is None
