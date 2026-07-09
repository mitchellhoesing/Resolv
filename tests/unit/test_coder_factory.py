"""Unit tests for the CoderBackend Protocol, factory, and prompt rendering."""

from __future__ import annotations

import re

import pytest
from pydantic import SecretStr

from resolv.adapters.claude_code_client import ClaudeCodeBackend
from resolv.adapters.coder import (
    CoderBackend,
    build_coder,
    dump_prompt_log,
    render_user_prompt,
)
from resolv.adapters.llm_inference import LiteLLMBackend
from resolv.core.state import ContextChunk, IssueRef
from resolv.exceptions import ConfigError


def test_build_coder_returns_claude_code_backend() -> None:
    backend = build_coder("claude_code", claude_model="claude-sonnet-4-6")
    assert isinstance(backend, ClaudeCodeBackend)
    assert isinstance(backend, CoderBackend)


def test_build_coder_forwards_anthropic_api_key() -> None:
    api_key = SecretStr("sk-ant-test")
    backend = build_coder(
        "claude_code", claude_model="claude-sonnet-4-6", anthropic_api_key=api_key
    )
    assert isinstance(backend, ClaudeCodeBackend)
    assert backend._anthropic_api_key is api_key


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


def test_render_user_prompt_includes_blame_provenance() -> None:
    issue = IssueRef(owner="a", repo="b", number=7, title="Boom", body="x", labels=())
    context = [
        ContextChunk(
            file_path="src/x.py",
            symbol="foo",
            snippet="def foo(): ...",
            provenance=("abc12345 2024-01-02 Alice — fix off-by-one",),
        )
    ]
    prompt = render_user_prompt(issue, context, prior_feedback=None)

    assert "Past changes to these lines" in prompt
    assert "abc12345 2024-01-02 Alice — fix off-by-one" in prompt


def test_render_user_prompt_handles_empty_body_and_context() -> None:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    prompt = render_user_prompt(issue, [], None)
    assert "(no body provided)" in prompt
    assert "(none extracted)" in prompt
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
