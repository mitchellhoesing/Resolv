"""Test Runner node — detects the target repo's test framework and runs it inside the sandbox."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from resolv.core.state import BlackboardState, IterationRecord
from resolv.utils.run_log import log_event
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
        command = detect_test_command(state.workspace_path)
        if command is None:
            log_event("[test_runner] error: no test runner detected")
            return _record_and_return(state, "FAILED", "no test runner detected")
        log_event(f"[test_runner] running: {' '.join(command)}")
        try:
            result = sandbox_runner(
                command,
                state.workspace_path,
                timeout=timeout,
            )
        except Exception as exc:
            log_event(f"[test_runner] error: {exc}")
            raise
        status = "PASSED" if result.exit_code == 0 else "FAILED"
        combined = (result.stdout + result.stderr)[-_OUTPUT_TAIL_CHARS:]
        log_event(_format_test_summary(combined, status))
        return _record_and_return(state, status, combined)

    return test_runner_node


def _format_test_summary(output: str, status: str) -> str:
    """Compose the log entry for a test run, with per-test counts when parseable."""
    counts = _parse_test_counts(output)
    if counts is None:
        return f"[test_runner] status {status}"
    passed_count, failed_count = counts
    return f"[test_runner] {passed_count} passed, {failed_count} failed — status {status}"


def _parse_test_counts(output: str) -> tuple[int, int] | None:
    """Extract (passed, failed) counts from pytest or unittest summary output."""
    passed_match = re.search(r"(\d+) passed", output)
    failed_match = re.search(r"(\d+) failed", output)
    errored_match = re.search(r"(\d+) errors?\b", output)
    if passed_match or failed_match or errored_match:
        passed_count = int(passed_match.group(1)) if passed_match else 0
        failed_count = (int(failed_match.group(1)) if failed_match else 0) + (
            int(errored_match.group(1)) if errored_match else 0
        )
        return passed_count, failed_count
    ran_match = re.search(r"Ran (\d+) tests?", output)
    if ran_match:
        total_count = int(ran_match.group(1))
        failed_count = sum(
            int(count) for count in re.findall(r"(?:failures|errors)=(\d+)", output)
        )
        return total_count - failed_count, failed_count
    return None


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
