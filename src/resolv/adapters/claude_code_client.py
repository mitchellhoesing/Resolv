"""Claude Agent SDK thin wrapper and Coder backend.

`ClaudeCodeClient` wraps the async `claude_agent_sdk.query` generator into
a single coroutine that consumes the message stream and returns the final
result text. `ClaudeCodeBackend` adapts it to the synchronous
`CoderBackend` Protocol via `asyncio.run`; the SDK does its own
multi-turn tool-use loop and edits files in the workspace directly.

The agent verifies its own work as it goes: `run_tests` is registered as an
in-process SDK MCP tool that delegates to the injected `run_suite` callable,
so the edit -> test -> fix cycle happens inside one warm session where the
workspace is already in context. `Bash` is deliberately not granted — the
untrusted suite must stay inside the sandbox `run_suite` applies rather than
running in this subprocess, whose environment carries the API key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    McpServerConfig,
    ResultMessage,
    SdkMcpTool,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from pydantic import SecretStr

from resolv.adapters.coder import render_user_prompt
from resolv.core.state import IssueRef
from resolv.exceptions import CoderError
from resolv.utils.run_log import log_event

_TOOL_SERVER_NAME = "resolv"
_RUN_TESTS_TOOL = "run_tests"
# SDK MCP tools are addressed by their namespaced name; the bare name does not
# authorize the call.
_RUN_TESTS_QUALIFIED = f"mcp__{_TOOL_SERVER_NAME}__{_RUN_TESTS_TOOL}"

_DEFAULT_ALLOWED_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "Grep",
    "Glob",
    _RUN_TESTS_QUALIFIED,
)

_SYSTEM_PROMPT = (
    "You are Resolv, an autonomous code-fix agent. Read the issue, explore "
    "the workspace as needed, and edit files in place to resolve the issue. "
    "Make the smallest change that addresses the reported problem. Run the "
    f"`{_RUN_TESTS_TOOL}` tool after editing and keep going — read the "
    "failures, refine the fix, run it again — until the suite passes. Fix the "
    "source rather than weakening the suite: only edit a test when the issue "
    "is that the test itself asserts the wrong behaviour. Stop once the tests "
    "pass."
)


def _make_run_tests_tool(
    run_suite: Callable[[Path], str], workspace_path: Path
) -> SdkMcpTool[Any]:
    """Wrap `run_suite` as the agent-callable `run_tests` tool."""

    @tool(
        _RUN_TESTS_TOOL,
        "Run the repository's test suite in an isolated sandbox and return its "
        "status and output. Takes no arguments.",
        {},
    )
    async def run_tests(args: dict[str, Any]) -> dict[str, Any]:
        # `run_suite` spawns a subprocess and blocks for up to the suite
        # timeout; off-loading it keeps the SDK's message stream responsive.
        report = await asyncio.to_thread(run_suite, workspace_path)
        return {"content": [{"type": "text", "text": report}]}

    return run_tests


class ClaudeCodeClient:
    async def run(
        self,
        prompt: str,
        *,
        system_prompt: str,
        cwd: Path,
        model: str,
        allowed_tools: tuple[str, ...] = _DEFAULT_ALLOWED_TOOLS,
        max_turns: int | None = None,
        env: dict[str, str] | None = None,
        mcp_servers: dict[str, McpServerConfig] | None = None,
    ) -> str:
        options = ClaudeAgentOptions(
            cwd=str(cwd),
            system_prompt=system_prompt,
            model=model,
            allowed_tools=list(allowed_tools),
            permission_mode="acceptEdits",
            max_turns=max_turns,
            env=env or {},
            mcp_servers=mcp_servers or {},
        )
        final_result = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage) and message.usage:
                tool_names = [
                    block.name
                    for block in message.content
                    if isinstance(block, ToolUseBlock)
                ]
                log_event(f"[coder] turn usage={message.usage} tools={tool_names}")
            elif isinstance(message, ResultMessage):
                log_event(
                    f"[coder] run complete: turns={message.num_turns} "
                    f"cost_usd={message.total_cost_usd} usage={message.usage}"
                )
                final_result = message.result or ""
        return final_result


class ClaudeCodeBackend:
    def __init__(
        self,
        client: ClaudeCodeClient,
        *,
        model: str,
        run_suite: Callable[[Path], str],
        max_turns: int,
        anthropic_api_key: SecretStr | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._run_suite = run_suite
        self._max_turns = max_turns
        self._anthropic_api_key = anthropic_api_key

    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
    ) -> None:
        user_prompt = render_user_prompt(issue)
        # Scope the key to the SDK subprocess only; an empty key is omitted so
        # local runs can fall back to the host's logged-in Claude credentials.
        sdk_env: dict[str, str] = {}
        if self._anthropic_api_key and self._anthropic_api_key.get_secret_value():
            sdk_env["ANTHROPIC_API_KEY"] = self._anthropic_api_key.get_secret_value()
        tool_servers: dict[str, McpServerConfig] = {
            _TOOL_SERVER_NAME: create_sdk_mcp_server(
                name=_TOOL_SERVER_NAME,
                tools=[_make_run_tests_tool(self._run_suite, workspace_path)],
            )
        }
        try:
            final_result = asyncio.run(
                self._client.run(
                    prompt=user_prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    cwd=workspace_path,
                    model=self._model,
                    max_turns=self._max_turns,
                    env=sdk_env or None,
                    mcp_servers=tool_servers,
                )
            )
        except Exception as exc:
            raise CoderError(f"Claude Code backend failed: {exc}") from exc
        # The closing message distinguishes "converged" from "ran out of turns".
        # With no retry loop, a stalled run is triaged by a human who needs to
        # know which of the two happened.
        log_event(f"[coder-agent] final message: {final_result or '(none)'}")
