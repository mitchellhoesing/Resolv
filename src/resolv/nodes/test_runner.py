"""Test Runner node — detects the target repo's test framework and runs it inside the sandbox."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from resolv.core.state import BlackboardState, IterationRecord
from resolv.utils.sandbox import run_isolated

_OUTPUT_TAIL_CHARS = 10000


def detect_test_command(workspace: Path) -> list[str] | None:
    """Pick the test invocation by inspecting the workspace.

    Detection order: pytest config → tox.ini → unittest. Returns None when
    no recognizable test layout is present.
    """
    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "[tool.pytest.ini_options]" in text:
            return ["pytest", "-q", "--tb=short"]
    if (workspace / "pytest.ini").is_file() or (workspace / "conftest.py").is_file():
        return ["pytest", "-q", "--tb=short"]
    if (workspace / "tox.ini").is_file():
        return ["tox", "-q"]
    tests_dir = workspace / "tests"
    if tests_dir.is_dir() and any(
        path.suffix == ".py" and path.name.startswith("test_")
        for path in tests_dir.rglob("*.py")
    ):
        return ["python", "-m", "unittest", "discover", "-s", "tests"]
    return None


def make_test_runner_node(
    *,
    timeout: int,
    sandbox_runner: Callable[..., Any] = run_isolated,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def test_runner_node(state: BlackboardState) -> dict[str, Any]:
        _timestamp = datetime.now(timezone.utc).strftime("%m/%d/%YT%H:%MZ")
        print(f'"timestamp": {_timestamp}')
        print('"node": Test Runner')
        print('"event": "Node Activated"')
        command = detect_test_command(state.workspace_path)
        if command is None:
            return _record_and_return(state, "FAILED", "no test runner detected")
        result = sandbox_runner(
            command,
            state.workspace_path,
            timeout=timeout,
        )
        status = "PASSED" if result.exit_code == 0 else "FAILED"
        combined = (result.stdout + result.stderr)[-_OUTPUT_TAIL_CHARS:]
        return _record_and_return(state, status, combined)

    return test_runner_node


def _record_and_return(
    state: BlackboardState, status: str, output: str
) -> dict[str, Any]:
    record = IterationRecord(
        iteration=state.iteration,
        diff=state.current_diff,
        test_status=status,  # type: ignore[arg-type]
        test_output=output,
    )
    return {
        "test_status": status,
        "test_output": output,
        "history": [*state.history, record],
    }
