"""Unit tests for the CoderBackend Protocol and prompt rendering."""

from __future__ import annotations

from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient
from resolv.adapters.coder import CoderBackend, render_user_prompt
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
