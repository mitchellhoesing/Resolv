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

from resolv.adapters.coder import render_user_prompt
from resolv.core.state import ContextChunk, IssueRef
from resolv.exceptions import CoderError

_DEFAULT_ALLOWED_TOOLS = ("Read", "Write", "Edit", "Grep", "Glob")

_SYSTEM_PROMPT = (
    "You are Resolv, an autonomous code-fix agent. Read the issue and the "
    "provided code context, explore the workspace as needed, and edit files "
    "in place to resolve the issue. Make the smallest change that addresses "
    "the reported problem. Do not attempt to run tests; a separate sandboxed "
    "test runner will verify your patch."
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
    ) -> str:
        options = ClaudeAgentOptions(
            cwd=str(cwd),
            system_prompt=system_prompt,
            model=model,
            allowed_tools=list(allowed_tools),
            permission_mode="acceptEdits",
            max_turns=max_turns,
        )
        final_result = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                final_result = getattr(message, "result", "") or ""
        return final_result


class ClaudeCodeBackend:
    def __init__(self, client: ClaudeCodeClient, *, model: str) -> None:
        self._client = client
        self._model = model

    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
        pruned_context: list[ContextChunk],
        prior_feedback: str | None,
    ) -> None:
        user_prompt = render_user_prompt(issue, pruned_context, prior_feedback)
        try:
            asyncio.run(
                self._client.run(
                    prompt=user_prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    cwd=workspace_path,
                    model=self._model,
                )
            )
        except Exception as exc:
            raise CoderError(f"Claude Code backend failed: {exc}") from exc
