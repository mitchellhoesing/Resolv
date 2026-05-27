"""Coder backend Protocol and selection factory.

A Coder backend takes an issue + workspace + pruned context and mutates
the workspace in place to apply a proposed fix. The orchestrator
captures the resulting diff after the call returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from resolv.core.state import ContextChunk, IssueRef


@runtime_checkable
class CoderBackend(Protocol):
    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
        pruned_context: list[ContextChunk],
        prior_feedback: str | None,
    ) -> None: ...


def build_coder(
    backend: str,
    *,
    claude_model: str = "claude-sonnet-4-6",
    litellm_model: str = "gpt-4o",
    litellm_api_key: SecretStr | None = None,
) -> CoderBackend:
    if backend == "claude_code":
        from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient

        return ClaudeCodeBackend(ClaudeCodeClient(), model=claude_model)
    if backend == "litellm":
        from resolv.adapters.llm_inference import LiteLLMBackend, LLMInferenceClient

        return LiteLLMBackend(LLMInferenceClient(model=litellm_model, api_key=litellm_api_key))
    raise ValueError(f"Unknown coder backend: {backend!r}")


def render_user_prompt(
    issue: IssueRef,
    pruned_context: list[ContextChunk],
    prior_feedback: str | None,
) -> str:
    """Compose the user-facing prompt shared by both Coder backends."""
    sections = [
        f"# Issue #{issue.number}: {issue.title}",
        "",
        issue.body or "(no body provided)",
        "",
        "## Relevant code context",
    ]
    if pruned_context:
        for chunk in pruned_context:
            sections.append(f"\n### {chunk.file_path} :: {chunk.symbol}\n```\n{chunk.snippet}\n```")
    else:
        sections.append("(none extracted)")
    if prior_feedback:
        sections.extend(["", "## Prior attempt feedback", prior_feedback])
    return "\n".join(sections)
