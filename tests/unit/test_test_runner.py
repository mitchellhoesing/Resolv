"""Unit tests for the test_runner node and framework detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.nodes.test_runner import (
    _parse_test_counts,
    detect_test_command,
    make_test_runner_node,
)
from resolv.utils.sandbox import SandboxResult


@pytest.fixture(autouse=True)
def _isolate_log_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _read_run_log(tmp_path: Path) -> str:
    return "\n".join(
        log_file.read_text(encoding="utf-8")
        for log_file in (tmp_path / "logs").glob("*.log")
    )


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


def test_node_passes_venv_path_when_venv_exists(state: BlackboardState) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    venv = state.workspace_path.parent / f"{state.workspace_path.name}__venv"
    venv.mkdir()
    runner = MagicMock(
        return_value=SandboxResult(exit_code=0, stdout="3 passed", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    node(state)
    assert runner.call_args.kwargs["venv_path"] == venv


def test_node_passes_no_venv_path_when_venv_absent(state: BlackboardState) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=0, stdout="3 passed", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    node(state)
    assert runner.call_args.kwargs["venv_path"] is None


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


def test_logs_per_test_counts_on_pass(state: BlackboardState, tmp_path: Path) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=0, stdout="3 passed", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    node(state)
    assert "[test_runner] 3 passed, 0 failed — status PASSED" in _read_run_log(tmp_path)


def test_logs_per_test_counts_on_fail(state: BlackboardState, tmp_path: Path) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=1, stdout="1 passed, 2 failed", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    node(state)
    assert "[test_runner] 1 passed, 2 failed — status FAILED" in _read_run_log(tmp_path)


def test_logs_status_only_when_counts_unparseable(
    state: BlackboardState, tmp_path: Path
) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(
        return_value=SandboxResult(exit_code=1, stdout="segfault", stderr="")
    )
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    node(state)
    assert "[test_runner] status FAILED" in _read_run_log(tmp_path)


def test_logs_error_when_no_framework(state: BlackboardState, tmp_path: Path) -> None:
    node = make_test_runner_node(timeout=1, sandbox_runner=MagicMock())
    node(state)
    assert "[test_runner] error: no test runner detected" in _read_run_log(tmp_path)


def test_sandbox_error_is_logged_and_reraised(
    state: BlackboardState, tmp_path: Path
) -> None:
    (state.workspace_path / "conftest.py").write_text("")
    runner = MagicMock(side_effect=RuntimeError("namespace unavailable"))
    node = make_test_runner_node(timeout=60, sandbox_runner=runner)
    with pytest.raises(RuntimeError, match="namespace unavailable"):
        node(state)
    assert "[test_runner] error: namespace unavailable" in _read_run_log(tmp_path)


def test_parse_counts_from_unittest_summary() -> None:
    output = "Ran 5 tests in 0.100s\n\nFAILED (failures=1, errors=1)"
    assert _parse_test_counts(output) == (3, 2)
