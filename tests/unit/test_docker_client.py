"""Unit tests for the docker-py sandbox wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException, ImageNotFound
from pytest_mock import MockerFixture

from resolv.exceptions import SandboxError
from resolv.utils.docker_client import SandboxResult, get_client, run_in_sandbox


def test_get_client_wraps_docker_exception(mocker: MockerFixture) -> None:
    mocker.patch(
        "resolv.utils.docker_client.docker.from_env",
        side_effect=DockerException("daemon down"),
    )
    with pytest.raises(SandboxError, match="daemon down"):
        get_client()


def test_run_in_sandbox_returns_result(mocker: MockerFixture, tmp_path: Path) -> None:
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [b"hello\n", b""]
    client = MagicMock()
    client.containers.run.return_value = container
    mocker.patch("resolv.utils.docker_client.docker.from_env", return_value=client)

    result = run_in_sandbox(["echo", "hi"], tmp_path, image_tag="resolv-sandbox:latest")

    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""

    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["image"] == "resolv-sandbox:latest"
    assert run_kwargs["command"] == ["echo", "hi"]
    assert run_kwargs["working_dir"] == "/workspace"
    assert run_kwargs["network_mode"] == "none"
    assert str(tmp_path.resolve()) in run_kwargs["volumes"]
    container.remove.assert_called_once_with(force=True)


def test_run_in_sandbox_raises_on_missing_image(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    client = MagicMock()
    client.containers.run.side_effect = ImageNotFound("missing")
    mocker.patch("resolv.utils.docker_client.docker.from_env", return_value=client)

    with pytest.raises(SandboxError, match="not built"):
        run_in_sandbox(["echo"], tmp_path, image_tag="absent:latest")


def test_run_in_sandbox_raises_on_timeout(mocker: MockerFixture, tmp_path: Path) -> None:
    container = MagicMock()
    container.wait.side_effect = RuntimeError("read timeout")
    client = MagicMock()
    client.containers.run.return_value = container
    mocker.patch("resolv.utils.docker_client.docker.from_env", return_value=client)

    with pytest.raises(SandboxError, match="timed out"):
        run_in_sandbox(["sleep", "999"], tmp_path, image_tag="x:latest", timeout=1)

    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)
