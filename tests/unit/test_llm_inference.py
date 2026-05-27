"""Unit tests for the LiteLLM wrapper and Coder backend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from resolv.adapters.llm_inference import LiteLLMBackend, LLMInferenceClient
from resolv.core.state import ContextChunk, IssueRef
from resolv.exceptions import CoderError

_VALID_DIFF = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(owner="a", repo="b", number=1, title="t", body="body", labels=())


def _completion_response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    return response


def test_client_complete_passes_model_and_messages(mocker: MockerFixture) -> None:
    fake = mocker.patch(
        "resolv.adapters.llm_inference.litellm.completion",
        return_value=_completion_response("hello"),
    )
    client = LLMInferenceClient(model="gpt-4o")
    out = client.complete("sys", "user")
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert kwargs["temperature"] == 0.0
    assert out == "hello"


def test_backend_applies_valid_diff_on_first_try(
    mocker: MockerFixture, tmp_path: Path, issue: IssueRef
) -> None:
    client = LLMInferenceClient(model="gpt-4o")
    mocker.patch.object(client, "complete", return_value=_VALID_DIFF)
    fake_run = mocker.patch(
        "resolv.adapters.llm_inference.subprocess.run",
        return_value=MagicMock(returncode=0, stderr=""),
    )

    LiteLLMBackend(client).generate_patch(issue, tmp_path, [], None)

    fake_run.assert_called_once()
    assert fake_run.call_args.kwargs["input"] == _VALID_DIFF
    assert fake_run.call_args.kwargs["cwd"] == str(tmp_path)


def test_backend_retries_then_succeeds_on_malformed_diff(
    mocker: MockerFixture, tmp_path: Path, issue: IssueRef
) -> None:
    client = LLMInferenceClient(model="gpt-4o")
    mocker.patch.object(client, "complete", side_effect=["not a diff", _VALID_DIFF])
    fake_run = mocker.patch(
        "resolv.adapters.llm_inference.subprocess.run",
        return_value=MagicMock(returncode=0, stderr=""),
    )

    LiteLLMBackend(client).generate_patch(issue, tmp_path, [], None)
    fake_run.assert_called_once()


def test_backend_raises_coder_error_after_max_attempts(
    mocker: MockerFixture, tmp_path: Path, issue: IssueRef
) -> None:
    client = LLMInferenceClient(model="gpt-4o")
    mocker.patch.object(client, "complete", return_value="garbage")
    mocker.patch("resolv.adapters.llm_inference.subprocess.run")

    backend = LiteLLMBackend(client, max_attempts=2)
    with pytest.raises(CoderError):
        backend.generate_patch(issue, tmp_path, [ContextChunk(file_path="x", symbol="y", snippet="z")], None)


def test_backend_surfaces_git_apply_error(
    mocker: MockerFixture, tmp_path: Path, issue: IssueRef
) -> None:
    client = LLMInferenceClient(model="gpt-4o")
    mocker.patch.object(client, "complete", return_value=_VALID_DIFF)
    mocker.patch(
        "resolv.adapters.llm_inference.subprocess.run",
        return_value=MagicMock(returncode=1, stderr="patch does not apply"),
    )

    backend = LiteLLMBackend(client, max_attempts=1)
    with pytest.raises(CoderError, match="patch does not apply"):
        backend.generate_patch(issue, tmp_path, [], None)
