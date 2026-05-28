"""Unit tests for the CoderBackend Protocol, factory, and prompt rendering."""

from __future__ import annotations

import pytest

from resolv.adapters.claude_code_client import ClaudeCodeBackend
from resolv.adapters.coder import CoderBackend, build_coder, render_user_prompt
from resolv.adapters.llm_inference import LiteLLMBackend
from resolv.core.state import ContextChunk, IssueRef
from resolv.exceptions import ConfigError


def test_build_coder_returns_claude_code_backend() -> None:
    backend = build_coder("claude_code", claude_model="claude-sonnet-4-6")
    assert isinstance(backend, ClaudeCodeBackend)
    assert isinstance(backend, CoderBackend)


def test_build_coder_returns_litellm_backend() -> None:
    backend = build_coder("litellm", litellm_model="gpt-4o")
    assert isinstance(backend, LiteLLMBackend)
    assert isinstance(backend, CoderBackend)


def test_build_coder_rejects_unknown_backend() -> None:
    with pytest.raises(ConfigError, match="Unknown coder backend"):
        build_coder("vibes")


def test_render_user_prompt_includes_issue_and_context() -> None:
    issue = IssueRef(
        owner="a", repo="b", number=7, title="Boom", body="repro steps", labels=("bug",)
    )
    context = [ContextChunk(file_path="src/x.py", symbol="foo", snippet="def foo(): ...")]
    prompt = render_user_prompt(issue, context, prior_feedback="prior attempt missed line 4")

    assert "Issue #7: Boom" in prompt
    assert "repro steps" in prompt
    assert "src/x.py :: foo" in prompt
    assert "def foo(): ..." in prompt
    assert "prior attempt missed line 4" in prompt


def test_render_user_prompt_handles_empty_body_and_context() -> None:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    prompt = render_user_prompt(issue, [], None)
    assert "(no body provided)" in prompt
    assert "(none extracted)" in prompt
    assert "Prior attempt feedback" not in prompt
