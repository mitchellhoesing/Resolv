"""Unit tests for the Claude Agent SDK wrapper and Coder backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient
from resolv.core.state import IssueRef
from resolv.exceptions import CoderError


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(owner="a", repo="b", number=1, title="t", body="body", labels=())


def _async_iter(items: list[Any]):
    async def gen():
        for item in items:
            yield item
    return gen()


def test_client_run_consumes_messages_and_returns_final_result(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    result_msg = MagicMock()
    result_msg.result = "done"
    mocker.patch(
        "resolv.adapters.claude_code_client.ResultMessage", new=type(result_msg)
    )
    mocker.patch(
        "resolv.adapters.claude_code_client.query",
        return_value=_async_iter([MagicMock(), result_msg]),
    )
    fake_options = mocker.patch("resolv.adapters.claude_code_client.ClaudeAgentOptions")

    client = ClaudeCodeClient()
    out = asyncio.run(
        client.run(prompt="p", system_prompt="s", cwd=tmp_path, model="claude-sonnet-4-6")
    )

    assert out == "done"
    fake_options.assert_called_once()
    kwargs = fake_options.call_args.kwargs
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system_prompt"] == "s"
    assert kwargs["permission_mode"] == "acceptEdits"
    assert "Bash" not in kwargs["allowed_tools"]


def test_client_run_passes_env_to_agent_options(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch(
        "resolv.adapters.claude_code_client.query",
        return_value=_async_iter([]),
    )
    fake_options = mocker.patch("resolv.adapters.claude_code_client.ClaudeAgentOptions")

    client = ClaudeCodeClient()
    asyncio.run(
        client.run(
            prompt="p",
            system_prompt="s",
            cwd=tmp_path,
            model="claude-sonnet-4-6",
            env={"ANTHROPIC_API_KEY": "sk-ant-test"},
        )
    )

    assert fake_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": "sk-ant-test"}


def test_backend_invokes_client_with_workspace(
    mocker: MockerFixture, tmp_path: Path, issue: IssueRef
) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def fake_run(**kwargs):
        fake_run.kwargs = kwargs
        return "ok"

    fake_run.kwargs = {}
    fake_client.run = fake_run

    ClaudeCodeBackend(fake_client, model="claude-opus-4-7").generate_patch(
        issue, tmp_path, None
    )

    assert fake_run.kwargs["cwd"] == tmp_path
    assert fake_run.kwargs["model"] == "claude-opus-4-7"
    assert "Issue #1" in fake_run.kwargs["prompt"]
    assert fake_run.kwargs["env"] is None


def test_backend_scopes_api_key_to_sdk_env(
    tmp_path: Path, issue: IssueRef
) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def fake_run(**kwargs):
        fake_run.kwargs = kwargs
        return "ok"

    fake_run.kwargs = {}
    fake_client.run = fake_run

    backend = ClaudeCodeBackend(
        fake_client, model="claude-opus-4-7", anthropic_api_key=SecretStr("sk-ant-test")
    )
    backend.generate_patch(issue, tmp_path, None)

    assert fake_run.kwargs["env"] == {"ANTHROPIC_API_KEY": "sk-ant-test"}


def test_backend_omits_env_for_empty_api_key(
    tmp_path: Path, issue: IssueRef
) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def fake_run(**kwargs):
        fake_run.kwargs = kwargs
        return "ok"

    fake_run.kwargs = {}
    fake_client.run = fake_run

    backend = ClaudeCodeBackend(
        fake_client, model="claude-opus-4-7", anthropic_api_key=SecretStr("")
    )
    backend.generate_patch(issue, tmp_path, None)

    assert fake_run.kwargs["env"] is None


def test_backend_wraps_sdk_errors_in_coder_error(
    tmp_path: Path, issue: IssueRef
) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def boom(**kwargs):
        raise RuntimeError("sdk crash")

    fake_client.run = boom

    with pytest.raises(CoderError, match="sdk crash"):
        ClaudeCodeBackend(fake_client, model="claude-opus-4-7").generate_patch(
            issue, tmp_path, None
        )
