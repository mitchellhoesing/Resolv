"""LiteLLM thin wrapper and Coder backend.

`LLMInferenceClient` is a single-method router around `litellm.completion`.
`LiteLLMBackend` adapts it to the `CoderBackend` Protocol by generating a
unified diff in one shot, validating it with `unidiff`, and applying it
via `git apply --3way`. Retries once on parse/apply failure.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import litellm
from pydantic import SecretStr
from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

from resolv.adapters.coder import render_user_prompt
from resolv.core.state import ContextChunk, IssueRef
from resolv.exceptions import CoderError

_SYSTEM_PROMPT = (
    "You are a code-fix assistant. Given an issue and code context, output a "
    "unified diff that resolves the issue when applied with `git apply --3way`.\n"
    "Output ONLY the raw diff text. No commentary. No markdown fences. No "
    "explanations before or after. The diff must include valid `--- a/...` and "
    "`+++ b/...` headers."
)


class LLMInferenceClient:
    def __init__(self, model: str, api_key: SecretStr | None = None) -> None:
        self._model = model
        self._api_key = api_key.get_secret_value() if api_key else None

    def complete(
        self, system_prompt: str, user_prompt: str, *, temperature: float = 0.0
    ) -> str:
        response = litellm.completion(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            api_key=self._api_key,
        )
        return response.choices[0].message.content or ""


class LiteLLMBackend:
    def __init__(self, client: LLMInferenceClient, *, max_attempts: int = 2) -> None:
        self._client = client
        self._max_attempts = max_attempts

    def generate_patch(
        self,
        issue: IssueRef,
        workspace_path: Path,
        pruned_context: list[ContextChunk],
        prior_feedback: str | None,
    ) -> None:
        user_prompt = render_user_prompt(issue, pruned_context, prior_feedback)
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            diff_text = self._client.complete(_SYSTEM_PROMPT, user_prompt)
            try:
                _validate_diff(diff_text)
                _apply_diff(diff_text, workspace_path)
                return
            except (UnidiffParseError, _DiffApplyError) as exc:
                last_error = exc
                user_prompt = (
                    f"{user_prompt}\n\n## Prior attempt failed\n{exc}\n"
                    "Please return a corrected unified diff only."
                )
        raise CoderError(
            f"LiteLLM backend failed after {self._max_attempts} attempts: {last_error}"
        ) from last_error


class _DiffApplyError(RuntimeError):
    pass


def _validate_diff(diff_text: str) -> None:
    if not diff_text.strip():
        raise UnidiffParseError("empty diff")
    PatchSet.from_string(diff_text)


def _apply_diff(diff_text: str, workspace_path: Path) -> None:
    result = subprocess.run(
        ["git", "apply", "--3way", "-"],
        input=diff_text,
        cwd=str(workspace_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise _DiffApplyError(result.stderr.strip() or "git apply failed")
