"""Unit tests for the Claude Agent SDK wrapper and Coder backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.adapters.claude_code_client import (
    _RUN_TESTS_QUALIFIED,
    ClaudeCodeBackend,
    ClaudeCodeClient,
    _make_run_tests_tool,
)
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


def _backend(client: Any, **overrides: Any) -> ClaudeCodeBackend:
    """Build a backend, defaulting the wiring a test isn't exercising."""
    kwargs: dict[str, Any] = {
        "model": "claude-opus-4-7",
        "run_suite": lambda workspace: "PASSED\n\n1 passed",
        "max_turns": 60,
    }
    kwargs.update(overrides)
    return ClaudeCodeBackend(client, **kwargs)


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

    _backend(fake_client).generate_patch(issue, tmp_path, None)

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

    backend = _backend(fake_client, anthropic_api_key=SecretStr("sk-ant-test"))
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

    backend = _backend(fake_client, anthropic_api_key=SecretStr(""))
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
        _backend(fake_client).generate_patch(issue, tmp_path, None)


def test_run_tests_tool_delegates_to_injected_run_suite(tmp_path: Path) -> None:
    called_with: list[Path] = []

    def run_suite(workspace: Path) -> str:
        called_with.append(workspace)
        return "FAILED\n\n2 failed"

    sdk_tool = _make_run_tests_tool(run_suite, tmp_path)
    result = asyncio.run(sdk_tool.handler({}))

    assert called_with == [tmp_path]
    assert result["content"] == [{"type": "text", "text": "FAILED\n\n2 failed"}]


def test_run_tests_tool_takes_no_arguments(tmp_path: Path) -> None:
    sdk_tool = _make_run_tests_tool(lambda workspace: "PASSED", tmp_path)
    assert sdk_tool.name == "run_tests"
    assert sdk_tool.input_schema == {}


def test_backend_registers_run_tests_server_and_authorizes_it(
    tmp_path: Path, issue: IssueRef
) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def fake_run(**kwargs):
        fake_run.kwargs = kwargs
        return "ok"

    fake_run.kwargs = {}
    fake_client.run = fake_run

    _backend(fake_client).generate_patch(issue, tmp_path, None)

    # The agent can only call the tool if the server is registered *and* the
    # namespaced name is allowed; the bare name would not authorize it.
    assert list(fake_run.kwargs["mcp_servers"]) == ["resolv"]
    assert _RUN_TESTS_QUALIFIED == "mcp__resolv__run_tests"


def test_backend_passes_max_turns_to_client(tmp_path: Path, issue: IssueRef) -> None:
    fake_client = MagicMock(spec=ClaudeCodeClient)

    async def fake_run(**kwargs):
        fake_run.kwargs = kwargs
        return "ok"

    fake_run.kwargs = {}
    fake_client.run = fake_run

    _backend(fake_client, max_turns=12).generate_patch(issue, tmp_path, None)

    # With no retry loop this is the only ceiling on one coder invocation.
    assert fake_run.kwargs["max_turns"] == 12


def test_client_grants_run_tests_but_never_bash(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch(
        "resolv.adapters.claude_code_client.query", return_value=_async_iter([])
    )
    fake_options = mocker.patch("resolv.adapters.claude_code_client.ClaudeAgentOptions")

    asyncio.run(
        ClaudeCodeClient().run(
            prompt="p", system_prompt="s", cwd=tmp_path, model="claude-opus-4-7"
        )
    )

    allowed = fake_options.call_args.kwargs["allowed_tools"]
    assert _RUN_TESTS_QUALIFIED in allowed
    # Bash would run the untrusted suite in this subprocess, which holds the key.
    assert "Bash" not in allowed
