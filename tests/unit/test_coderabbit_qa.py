"""Unit tests for the CodeRabbit QA node."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.nodes.coderabbit_qa import make_coderabbit_qa_node
from resolv.utils.docker_client import SandboxResult


@pytest.fixture
def state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    return BlackboardState(issue=issue, workspace_path=tmp_path)


def test_approves_on_zero_exit_with_empty_stdout(state: BlackboardState) -> None:
    runner = MagicMock(return_value=SandboxResult(exit_code=0, stdout="", stderr=""))
    node = make_coderabbit_qa_node(image_tag="x", timeout=30, sandbox_runner=runner)
    assert node(state) == {"qa_status": "APPROVED", "qa_findings": []}
    kwargs = runner.call_args.kwargs
    assert kwargs["network"] == "bridge"
    assert kwargs["image_tag"] == "x"
    assert runner.call_args.args[0] == ["coderabbit", "review", "--plain"]


def test_rejects_with_findings_from_stdout(state: BlackboardState) -> None:
    runner = MagicMock(
        return_value=SandboxResult(
            exit_code=1, stdout="src/x.py:3 missing return\nsrc/y.py:4 unused import\n", stderr=""
        )
    )
    node = make_coderabbit_qa_node(image_tag="x", timeout=30, sandbox_runner=runner)
    result = node(state)
    assert result["qa_status"] == "REJECTED"
    assert result["qa_findings"] == [
        "src/x.py:3 missing return",
        "src/y.py:4 unused import",
    ]


def test_rejects_with_stderr_when_stdout_silent(state: BlackboardState) -> None:
    runner = MagicMock(
        return_value=SandboxResult(exit_code=2, stdout="", stderr="auth failed\n")
    )
    node = make_coderabbit_qa_node(image_tag="x", timeout=30, sandbox_runner=runner)
    result = node(state)
    assert result["qa_status"] == "REJECTED"
    assert result["qa_findings"] == ["auth failed"]
