"""Unit tests for the per-issue container dispatch module."""

from __future__ import annotations

from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.config import Settings
from resolv.dispatch import build_dispatch_command, dispatch_issue


def _settings() -> Settings:
    return Settings(
        github_token=SecretStr("ghp_secret"),
        anthropic_api_key=SecretStr("sk-secret"),
    )


def test_build_dispatch_command_shape() -> None:
    command = build_dispatch_command(_settings(), "acme", "widgets", 7)

    assert command[:4] == ["docker", "run", "--rm", "--cap-add=SYS_ADMIN"]
    assert "resolv-sandbox:latest" in command
    assert command[-5:] == ["run", "--repo", "acme/widgets", "--issue", "7"]
    # Secrets are passed through env by name only, never as argv values.
    assert "ghp_secret" not in command
    assert "sk-secret" not in command


def test_dispatch_issue_injects_secrets_and_returns_exit_code(
    mocker: MockerFixture,
) -> None:
    run_mock = mocker.patch("resolv.dispatch.subprocess.run")
    run_mock.return_value.returncode = 3

    exit_code = dispatch_issue(_settings(), "acme", "widgets", 7)

    assert exit_code == 3
    run_mock.assert_called_once()
    command, kwargs = run_mock.call_args.args[0], run_mock.call_args.kwargs
    assert command == build_dispatch_command(_settings(), "acme", "widgets", 7)
    assert kwargs["check"] is False
    assert kwargs["env"]["RESOLV_GITHUB_TOKEN"] == "ghp_secret"
    assert kwargs["env"]["RESOLV_ANTHROPIC_API_KEY"] == "sk-secret"


def test_build_dispatch_command_omits_dry_run_by_default() -> None:
    command = build_dispatch_command(_settings(), "acme", "widgets", 7)
    assert "--dry-run" not in command


def test_build_dispatch_command_appends_dry_run_when_requested() -> None:
    command = build_dispatch_command(
        _settings(), "acme", "widgets", 7, dry_run=True
    )
    assert command[-6:] == [
        "run", "--repo", "acme/widgets", "--issue", "7", "--dry-run",
    ]


def test_dispatch_issue_forwards_dry_run_to_command(mocker: MockerFixture) -> None:
    run_mock = mocker.patch("resolv.dispatch.subprocess.run")
    run_mock.return_value.returncode = 0

    dispatch_issue(_settings(), "acme", "widgets", 7, dry_run=True)

    command = run_mock.call_args.args[0]
    assert "--dry-run" in command
