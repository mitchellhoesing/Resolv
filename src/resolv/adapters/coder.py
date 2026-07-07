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
from resolv.exceptions import ConfigError


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
    claude_model: str | None = None,
    anthropic_api_key: SecretStr | None = None,
    litellm_model: str | None = None,
    litellm_api_key: SecretStr | None = None,
) -> CoderBackend:
    if backend == "claude_code":
        if claude_model is None:
            raise ConfigError("claude_model is required when backend='claude_code'")
        from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient

        return ClaudeCodeBackend(
            ClaudeCodeClient(), model=claude_model, anthropic_api_key=anthropic_api_key
        )
    if backend == "litellm":
        if litellm_model is None:
            raise ConfigError("litellm_model is required when backend='litellm'")
        from resolv.adapters.llm_inference import LiteLLMBackend, LLMInferenceClient

        return LiteLLMBackend(LLMInferenceClient(model=litellm_model, api_key=litellm_api_key))
    raise ConfigError(f"Unknown coder backend: {backend!r}")


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
        "## Candidate starting points (may be irrelevant; verify before relying on these)",
    ]
    if pruned_context:
        for chunk in pruned_context:
            block = f"\n### {chunk.file_path} :: {chunk.symbol}\n```\n{chunk.snippet}\n```"
            if chunk.provenance:
                block += "\nPast changes to these lines (git blame, most recent first):\n" + "\n".join(
                    f"- {entry}" for entry in chunk.provenance
                )
            sections.append(block)
    else:
        sections.append("(none extracted)")
    if prior_feedback:
        sections.extend(["", "## Prior attempt feedback", prior_feedback])
    return "\n".join(sections)
