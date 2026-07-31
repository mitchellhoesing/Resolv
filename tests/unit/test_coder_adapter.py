"""Unit tests for the CoderBackend Protocol and prompt rendering."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

import resolv.adapters.claude_code_client as claude_code_client_module
from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient
from resolv.adapters.coder import CoderBackend, render_user_prompt
from resolv.core.state import IssueRef


def _backend(**overrides: Any) -> ClaudeCodeBackend:
    """Build a backend, defaulting the wiring a test isn't exercising."""
    kwargs: dict[str, Any] = {
        "model": "claude-sonnet-4-6",
        "run_suite": lambda workspace: "PASSED\n\n1 passed",
        "max_turns": 60,
    }
    kwargs.update(overrides)
    return ClaudeCodeBackend(ClaudeCodeClient(), **kwargs)


def test_claude_code_backend_satisfies_protocol() -> None:
    assert isinstance(_backend(), CoderBackend)


def test_render_user_prompt_includes_the_issue() -> None:
    issue = IssueRef(
        owner="a", repo="b", number=7, title="Boom", body="repro steps", labels=("bug",)
    )
    prompt = render_user_prompt(issue)

    assert "Issue #7: Boom" in prompt
    assert "repro steps" in prompt


def test_render_user_prompt_handles_empty_body() -> None:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    assert "(no body provided)" in render_user_prompt(issue)


def test_generate_patch_logs_token_usage_not_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    turn_usage = {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 900}
    run_usage = {"input_tokens": 5000, "output_tokens": 400, "cache_read_input_tokens": 3600}

    def fake_query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        async def stream() -> AsyncIterator[Any]:
            yield AssistantMessage(
                content=[ToolUseBlock(id="tu_1", name="Read", input={"file_path": "f.py"})],
                model="claude-sonnet-4-6",
                usage=turn_usage,
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=10,
                duration_api_ms=8,
                is_error=False,
                num_turns=2,
                session_id="s1",
                total_cost_usd=0.05,
                usage=run_usage,
                result="done",
            )

        return stream()

    monkeypatch.setattr(claude_code_client_module, "query", fake_query)

    issue = IssueRef(
        owner="a", repo="b", number=7, title="Boom", body="repro steps", labels=()
    )
    _backend().generate_patch(issue=issue, workspace_path=tmp_path)

    log_contents = "\n".join(
        log_file.read_text(encoding="utf-8")
        for log_file in (tmp_path / "logs").glob("*.log")
    )
    assert f"[coder] turn usage={turn_usage} tools=['Read']" in log_contents
    assert (
        f"[coder] run complete: turns=2 cost_usd=0.05 usage={run_usage}"
        in log_contents
    )
    assert "repro steps" not in log_contents
