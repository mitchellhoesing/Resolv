"""Claude Agent SDK thin wrapper and Coder backend.

`ClaudeCodeClient` wraps the async `claude_agent_sdk.query` generator into
a single coroutine that consumes the message stream and returns the final
result text. `ClaudeCodeBackend` adapts it to the synchronous
`CoderBackend` Protocol via `asyncio.run`; the SDK does its own
multi-turn tool-use loop and edits files in the workspace directly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from pydantic import SecretStr

from resolv.adapters.coder import dump_prompt_log, render_user_prompt
from resolv.core.state import IssueRef
from resolv.exceptions import CoderError

_DEFAULT_ALLOWED_TOOLS = ("Read", "Write", "Edit", "Grep", "Glob")

_SYSTEM_PROMPT = (
    "You are Resolv, an autonomous code-fix agent. Read the issue, explore "
    "the workspace as needed, and edit files in place to resolve the issue. "
    "Make the smallest change that addresses the reported problem. Do not "
    "attempt to run tests; a separate sandboxed test runner will verify "
    "your patch."
)


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
    ) -> str:
        options = ClaudeAgentOptions(
            cwd=str(cwd),
            system_prompt=system_prompt,
            model=model,
            allowed_tools=list(allowed_tools),
            permission_mode="acceptEdits",
            max_turns=max_turns,
            env=env or {},
        )
        final_result = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                final_result = getattr(message, "result", "") or ""
        return final_result


class ClaudeCodeBackend:
    def __init__(
        self,
        client: ClaudeCodeClient,
        *,
        model: str,
        anthropic_api_key: SecretStr | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._anthropic_api_key = anthropic_api_key

    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
        pruned_context: list[ContextChunk],
        prior_feedback: str | None,
    ) -> None:
        user_prompt = render_user_prompt(issue, pruned_context, prior_feedback)
        dump_prompt_log(user_prompt)
        # Scope the key to the SDK subprocess only; an empty key is omitted so
        # local runs can fall back to the host's logged-in Claude credentials.
        sdk_env: dict[str, str] = {}
        if self._anthropic_api_key and self._anthropic_api_key.get_secret_value():
            sdk_env["ANTHROPIC_API_KEY"] = self._anthropic_api_key.get_secret_value()
        try:
            asyncio.run(
                self._client.run(
                    prompt=user_prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    cwd=workspace_path,
                    model=self._model,
                    env=sdk_env or None,
                )
            )
        except Exception as exc:
            raise CoderError(f"Claude Code backend failed: {exc}") from exc
