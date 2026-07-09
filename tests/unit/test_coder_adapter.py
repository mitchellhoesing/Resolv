"""Unit tests for the CoderBackend Protocol, prompt rendering, and prompt logging."""

from __future__ import annotations

import re

import pytest

from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient
from resolv.adapters.coder import (
    CoderBackend,
    dump_prompt_log,
    render_user_prompt,
)
from resolv.core.state import IssueRef


def test_claude_code_backend_satisfies_protocol() -> None:
    backend = ClaudeCodeBackend(ClaudeCodeClient(), model="claude-sonnet-4-6")
    assert isinstance(backend, CoderBackend)


def test_render_user_prompt_includes_issue_and_feedback() -> None:
    issue = IssueRef(
        owner="a", repo="b", number=7, title="Boom", body="repro steps", labels=("bug",)
    )
    prompt = render_user_prompt(issue, prior_feedback="prior attempt missed line 4")

    assert "Issue #7: Boom" in prompt
    assert "repro steps" in prompt
    assert "prior attempt missed line 4" in prompt


def test_render_user_prompt_handles_empty_body_and_feedback() -> None:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    prompt = render_user_prompt(issue, None)
    assert "(no body provided)" in prompt
    assert "Prior attempt feedback" not in prompt


def test_dump_prompt_log_appends_to_timestamped_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dump_prompt_log("first prompt")
    dump_prompt_log("second prompt")

    log_files = list((tmp_path / "logs").glob("*.log"))
    assert len(log_files) == 1
    # DD-MM-YYYYTHH-MMZ, e.g. 08-07-2026T14-32Z
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4}T\d{2}-\d{2}Z\.log", log_files[0].name)
    contents = log_files[0].read_text(encoding="utf-8")
    assert "first prompt" in contents
    assert "second prompt" in contents
