"""Unit tests for the in-process isolated test runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from resolv.exceptions import SandboxError
from resolv.utils.sandbox import SandboxResult, run_isolated, run_networked


def test_run_isolated_wraps_command_in_unshare_with_scrubbed_env(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict(
        "resolv.utils.sandbox.os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "RESOLV_GITHUB_TOKEN": "ghp_secret",
            "ANTHROPIC_API_KEY": "sk-secret",
        },
        clear=True,
    )
    run = mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="3 passed", stderr=""),
    )

    result = run_isolated(["pytest", "-q"], tmp_path, timeout=60)

    assert result == SandboxResult(exit_code=0, stdout="3 passed", stderr="")
    args, kwargs = run.call_args
    invoked = args[0]
    assert invoked[:3] == ["unshare", "--net", "--"]
    assert invoked[-2:] == ["pytest", "-q"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 60
    # Secrets must never reach the untrusted child.
    passed_env = kwargs["env"]
    assert passed_env == {"PATH": "/usr/bin", "HOME": "/root"}
    assert "RESOLV_GITHUB_TOKEN" not in passed_env
    assert "ANTHROPIC_API_KEY" not in passed_env


def test_run_isolated_reports_timeout_as_failure(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=5, output="partial"),
    )

    result = run_isolated(["pytest"], tmp_path, timeout=5)

    assert result.exit_code == -1
    assert result.stdout == "partial"
    assert "timed out after 5s" in result.stderr


def test_run_isolated_raises_when_unshare_missing(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        side_effect=FileNotFoundError("unshare"),
    )

    with pytest.raises(SandboxError, match="isolation tooling unavailable"):
        run_isolated(["pytest"], tmp_path, timeout=5)


def test_run_isolated_applies_venv_overlay(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    run = mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="", stderr=""),
    )
    venv_path = tmp_path / "repo__venv"

    run_isolated(["pytest"], tmp_path, timeout=5, venv_path=venv_path)

    passed_env = run.call_args.kwargs["env"]
    assert passed_env["PATH"] == f"{venv_path}/bin:/usr/bin"
    assert passed_env["VIRTUAL_ENV"] == str(venv_path)


def test_run_networked_runs_without_unshare_with_scrubbed_env(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict(
        "resolv.utils.sandbox.os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "RESOLV_GITHUB_TOKEN": "ghp_secret",
            "ANTHROPIC_API_KEY": "sk-secret",
        },
        clear=True,
    )
    run = mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="installed", stderr=""),
    )

    result = run_networked(["pip", "install", "-r", "requirements.txt"], tmp_path, timeout=60)

    assert result == SandboxResult(exit_code=0, stdout="installed", stderr="")
    args, kwargs = run.call_args
    invoked = args[0]
    assert invoked == ["pip", "install", "-r", "requirements.txt"]
    assert "unshare" not in invoked
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 60
    # Secrets must never reach the untrusted install either.
    passed_env = kwargs["env"]
    assert passed_env == {"PATH": "/usr/bin", "HOME": "/root"}
    assert "RESOLV_GITHUB_TOKEN" not in passed_env
    assert "ANTHROPIC_API_KEY" not in passed_env


def test_run_networked_applies_venv_overlay_and_extra_env(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    run = mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="", stderr=""),
    )
    venv_path = tmp_path / "repo__venv"

    run_networked(
        ["poetry", "install"],
        tmp_path,
        timeout=60,
        venv_path=venv_path,
        extra_env={"POETRY_VIRTUALENVS_CREATE": "false"},
    )

    passed_env = run.call_args.kwargs["env"]
    assert passed_env["PATH"] == f"{venv_path}/bin:/usr/bin"
    assert passed_env["VIRTUAL_ENV"] == str(venv_path)
    assert passed_env["POETRY_VIRTUALENVS_CREATE"] == "false"


def test_run_networked_reports_timeout_as_failure(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=5, output="partial"),
    )

    result = run_networked(["pip", "install"], tmp_path, timeout=5)

    assert result.exit_code == -1
    assert result.stdout == "partial"
    assert "timed out after 5s" in result.stderr


def test_run_networked_raises_when_tool_missing(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.dict("resolv.utils.sandbox.os.environ", {"PATH": "/usr/bin"}, clear=True)
    mocker.patch(
        "resolv.utils.sandbox.subprocess.run",
        side_effect=FileNotFoundError("poetry"),
    )

    with pytest.raises(SandboxError, match="install tooling unavailable"):
        run_networked(["poetry", "install"], tmp_path, timeout=5)
