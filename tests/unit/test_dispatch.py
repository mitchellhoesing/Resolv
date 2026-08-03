"""Unit tests for the per-issue container dispatch module."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pytest_mock import MockerFixture

from resolv.config import Settings
from resolv.dispatch import (
    build_dispatch_command,
    dispatch_issue,
    host_log_directory,
)


def _settings() -> Settings:
    return Settings(
        github_token=SecretStr("ghp_secret"),
        anthropic_api_key=SecretStr("sk-secret"),
        claude_code_oauth_token=SecretStr("oauth_secret"),
    )


def test_build_dispatch_command_shape() -> None:
    command = build_dispatch_command(_settings(), "acme", "widgets", 7)

    assert command[:4] == ["docker", "run", "--rm", "--cap-add=SYS_ADMIN"]
    assert "resolv-sandbox:latest" in command
    assert command[-5:] == ["run", "--repo", "acme/widgets", "--issue", "7"]
    # Secrets are passed through env by name only, never as argv values.
    assert "ghp_secret" not in command
    assert "sk-secret" not in command
    assert "oauth_secret" not in command


def test_build_dispatch_command_mounts_the_log_directory() -> None:
    """The container is --rm, so its logs must land on the host to survive."""
    command = build_dispatch_command(_settings(), "acme", "widgets", 7)

    mount = f"{host_log_directory('acme', 'widgets', 7)}:/workspace/logs"
    assert "-v" in command
    assert command[command.index("-v") + 1] == mount
    # The mount must precede the image name, or docker reads it as a container arg.
    assert command.index("-v") < command.index("resolv-sandbox:latest")


def test_host_log_directory_is_per_issue() -> None:
    """Consecutive issues must not interleave into the same per-minute log files."""
    first = host_log_directory("acme", "widgets", 7)
    second = host_log_directory("acme", "widgets", 9)

    assert first != second
    assert first.name == "acme__widgets__issue-7"
    assert first.parent == second.parent == Path("logs").resolve()


def test_dispatch_issue_creates_the_host_log_directory(mocker: MockerFixture) -> None:
    run_mock = mocker.patch("resolv.dispatch.subprocess.run")
    run_mock.return_value.returncode = 0
    # conftest chdirs each test into tmp_path, so this resolves under it.
    assert not Path("logs").exists()

    dispatch_issue(_settings(), "acme", "widgets", 7)

    assert (Path("logs") / "acme__widgets__issue-7").is_dir()


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
    assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth_secret"


def test_build_dispatch_command_forwards_dry_run_flag() -> None:
    """`resolv dispatch --dry-run` must reach the in-container `resolv run`."""
    command = build_dispatch_command(
        _settings(), "acme", "widgets", 7, dry_run=True
    )

    assert command[-6:] == [
        "run", "--repo", "acme/widgets", "--issue", "7", "--dry-run"
    ]


def test_build_dispatch_command_omits_dry_run_flag_by_default() -> None:
    command = build_dispatch_command(_settings(), "acme", "widgets", 7)

    assert "--dry-run" not in command


def test_dispatch_issue_forwards_dry_run_flag(mocker: MockerFixture) -> None:
    run_mock = mocker.patch("resolv.dispatch.subprocess.run")
    run_mock.return_value.returncode = 0

    dispatch_issue(_settings(), "acme", "widgets", 7, dry_run=True)

    command = run_mock.call_args.args[0]
    assert "--dry-run" in command
