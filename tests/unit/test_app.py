"""Unit tests for the production graph wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.config import Settings
from resolv.core.app import build_production_graph


def _patched_settings(**overrides: object) -> Settings:
    base = Settings(github_token=SecretStr("ghp_fake"))
    return base.model_copy(update=overrides)


def test_build_production_graph_wires_all_nodes(mocker: MockerFixture) -> None:
    mocker.patch("resolv.core.app.GitHubClient", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeBackend", return_value=MagicMock())
    mocker.patch("resolv.core.app.ClaudeCodeClient", return_value=MagicMock())
    fake_build_graph = mocker.patch(
        "resolv.core.app.build_graph", return_value=MagicMock()
    )

    settings = _patched_settings()
    build_production_graph(settings)

    fake_build_graph.assert_called_once()
    kwargs = fake_build_graph.call_args.kwargs
    assert set(kwargs) == {
        "context_broker_fn",
        "coder_fn",
        "test_runner_fn",
        "deliver_fn",
        "max_iterations",
    }
    assert kwargs["max_iterations"] == settings.loop.max_iterations
    for key in ("context_broker_fn", "coder_fn", "test_runner_fn", "deliver_fn"):
        assert callable(kwargs[key])
