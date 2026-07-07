"""Unit tests for the test_runner node and framework detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.nodes.test_runner import detect_test_command, make_test_runner_node
from resolv.utils.sandbox import SandboxResult


@pytest.fixture
def state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def test_detects_pyproject_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'\n")
    assert detect_test_command(tmp_path) == ["pytest", "-q", "--tb=short"]


def test_detects_conftest_only(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("")
    assert detect_test_command(tmp_path) == ["pytest", "-q", "--tb=short"]


def test_detects_tox_when_no_pytest_signals(tmp_path: Path) -> None:
    (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py310\n")
    assert detect_test_command(tmp_path) == ["tox", "-q"]


def test_detects_unittest_fallback(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("import unittest\n")
    assert detect_test_command(tmp_path) == ["python", "-m", "unittest", "discover", "-s", "tests"]


def test_no_detection_returns_none(tmp_path: Path) -> None:
    assert detect_test_command(tmp_path) is None


def test_node_marks_failed_when_no_framework(state: BlackboardState) -> None:
    runner = MagicMock()
    node = make_test_runner_node(timeout=1, sandbox_runner=runner)
    result = node(state)
    assert result["test_status"] == "FAILED"
    assert "no test runner detected" in result["test_output"]
    assert len(result["history"]) == 1
    runner.assert_not_called()


def test_node_marks_passed_on_zero_exit(state: BlackboardState) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=0, stdout="3 passed", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    result = node(state)
    assert result["test_status"] == "PASSED"
    assert "3 passed" in result["test_output"]
    runner.assert_called_once()
    call_kwargs = runner.call_args.kwargs
    assert call_kwargs["timeout"] == 60


def test_node_marks_failed_on_nonzero_exit(state: BlackboardState) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=1, stdout="2 failed", stderr="trace")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    result = node(state)
    assert result["test_status"] == "FAILED"
    assert "2 failed" in result["test_output"]
    assert "trace" in result["test_output"]
