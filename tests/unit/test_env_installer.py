"""Unit tests for the env_installer node and dependency-manifest detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resolv.core.state import BlackboardState, IssueRef
from resolv.exceptions import InstallError
from resolv.nodes.env_installer import (
    InstallStep,
    detect_install_plan,
    make_env_installer_node,
    venv_path_for,
)
from resolv.utils.sandbox import SandboxResult


@pytest.fixture(autouse=True)
def _isolate_log_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _read_run_log(tmp_path: Path) -> str:
    return "\n".join(
        log_file.read_text(encoding="utf-8")
        for log_file in (tmp_path / "logs").glob("*.log")
    )


@pytest.fixture
def state(tmp_path: Path) -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title="t", body="", labels=())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return BlackboardState(issue=issue, workspace_path=workspace)


@pytest.fixture
def venv(tmp_path: Path) -> Path:
    return tmp_path / "workspace__venv"


def _ok_runner() -> MagicMock:
    return MagicMock(return_value=SandboxResult(exit_code=0, stdout="", stderr=""))


# --- venv convention ---


def test_venv_path_is_sibling_of_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "acme__widgets__issue-42"
    assert venv_path_for(workspace) == tmp_path / "acme__widgets__issue-42__venv"


# --- detection: manager tier ---


def test_detects_poetry_from_lockfile(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "poetry.lock").write_text("")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=["poetry", "install", "--no-interaction"],
            label="poetry install",
            extra_env={"POETRY_VIRTUALENVS_CREATE": "false"},
        )
    ]


def test_detects_poetry_from_pyproject_section(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'x'\n")
    plan = detect_install_plan(tmp_path, venv)
    assert len(plan) == 1
    assert plan[0].label == "poetry install"


def test_detects_uv_from_lockfile(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "uv.lock").write_text("")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=["uv", "sync", "--frozen"],
            label="uv sync",
            extra_env={"UV_PROJECT_ENVIRONMENT": str(venv)},
        )
    ]


def test_detects_pipenv_sync_from_lockfile(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "Pipfile.lock").write_text("{}")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(command=["pipenv", "sync", "--dev"], label="pipenv sync")
    ]


def test_detects_pipenv_install_without_lockfile(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "Pipfile").write_text("")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(command=["pipenv", "install", "--dev"], label="pipenv install")
    ]


def test_poetry_wins_over_uv_and_requirements(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "poetry.lock").write_text("")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "requirements.txt").write_text("requests\n")
    plan = detect_install_plan(tmp_path, venv)
    assert [step.label for step in plan] == ["poetry install"]


# --- detection: pip tier ---


def test_detects_pyproject_with_test_extras(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\nversion = '0'\n"
        "[project.optional-dependencies]\n"
        "dev = ['ruff']\ntest = ['pytest']\ndocs = ['sphinx']\n"
    )
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=[f"{venv}/bin/python", "-m", "pip", "install", "-e", ".[dev,test]"],
            label="pip install",
        )
    ]


def test_detects_pyproject_without_test_extras(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=[f"{venv}/bin/python", "-m", "pip", "install", "-e", "."],
            label="pip install",
        )
    ]


def test_detects_setup_py_only(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=[f"{venv}/bin/python", "-m", "pip", "install", "-e", "."],
            label="pip install",
        )
    ]


def test_combines_requirements_files_into_one_command(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    assert detect_install_plan(tmp_path, venv) == [
        InstallStep(
            command=[
                f"{venv}/bin/python",
                "-m",
                "pip",
                "install",
                "-r",
                "requirements.txt",
                "-r",
                "requirements-dev.txt",
            ],
            label="pip install",
        )
    ]


def test_includes_requirements_directory_glob_sorted(tmp_path: Path, venv: Path) -> None:
    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    (requirements_dir / "test.txt").write_text("pytest\n")
    (requirements_dir / "base.txt").write_text("requests\n")
    plan = detect_install_plan(tmp_path, venv)
    assert plan[0].command[-4:] == ["-r", "requirements/base.txt", "-r", "requirements/test.txt"]


def test_empty_repo_yields_empty_plan(tmp_path: Path, venv: Path) -> None:
    assert detect_install_plan(tmp_path, venv) == []


def test_broken_pyproject_falls_back_to_setup_py(tmp_path: Path, venv: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not [valid toml")
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
    plan = detect_install_plan(tmp_path, venv)
    assert plan[0].command[-2:] == ["-e", "."]


# --- node behavior ---


def test_node_creates_venv_seeds_pytest_then_installs(
    state: BlackboardState, venv: Path
) -> None:
    (state.workspace_path / "requirements.txt").write_text("requests\n")
    runner = _ok_runner()
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    result = node(state)

    assert result == {}
    commands = [call.args[0] for call in runner.call_args_list]
    assert commands[0][1:] == ["-m", "venv", str(venv)]
    assert commands[1] == [f"{venv}/bin/python", "-m", "pip", "install", "pytest"]
    assert commands[2][-2:] == ["-r", "requirements.txt"]
    # venv creation runs without the overlay; later steps target the venv.
    assert runner.call_args_list[0].kwargs["venv_path"] is None
    assert runner.call_args_list[1].kwargs["venv_path"] == venv
    assert runner.call_args_list[2].kwargs["venv_path"] == venv
    assert all(call.kwargs["timeout"] == 900 for call in runner.call_args_list)


def test_node_passes_step_extra_env(state: BlackboardState) -> None:
    (state.workspace_path / "poetry.lock").write_text("")
    runner = _ok_runner()
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    node(state)

    poetry_call = runner.call_args_list[-1]
    assert poetry_call.kwargs["extra_env"] == {"POETRY_VIRTUALENVS_CREATE": "false"}


def test_node_skips_venv_creation_when_present(
    state: BlackboardState, venv: Path
) -> None:
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    runner = _ok_runner()
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    node(state)

    first_command = runner.call_args_list[0].args[0]
    assert first_command == [f"{venv}/bin/python", "-m", "pip", "install", "pytest"]


def test_node_proceeds_when_no_manifests(
    state: BlackboardState, tmp_path: Path
) -> None:
    runner = _ok_runner()
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    result = node(state)

    assert result == {}
    # venv creation + pytest seed only.
    assert runner.call_count == 2
    assert "no dependency manifests detected" in _read_run_log(tmp_path)


def test_node_raises_install_error_on_nonzero_exit(state: BlackboardState) -> None:
    (state.workspace_path / "requirements.txt").write_text("requests\n")
    results = [
        SandboxResult(exit_code=0, stdout="", stderr=""),  # venv creation
        SandboxResult(exit_code=0, stdout="", stderr=""),  # pytest seed
        SandboxResult(exit_code=1, stdout="boom", stderr="resolution failed"),
    ]
    runner = MagicMock(side_effect=results)
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    with pytest.raises(InstallError, match="pip install failed \\(exit 1\\)"):
        node(state)


def test_node_raises_install_error_on_timeout(state: BlackboardState) -> None:
    (state.workspace_path / "requirements.txt").write_text("requests\n")
    results = [
        SandboxResult(exit_code=0, stdout="", stderr=""),
        SandboxResult(exit_code=0, stdout="", stderr=""),
        SandboxResult(exit_code=-1, stdout="", stderr="command timed out after 900s"),
    ]
    runner = MagicMock(side_effect=results)
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    with pytest.raises(InstallError, match="timed out"):
        node(state)


def test_node_removes_lockfile_generated_by_install(state: BlackboardState) -> None:
    (state.workspace_path / "Pipfile").write_text("")
    generated_lockfile = state.workspace_path / "Pipfile.lock"

    def runner_side_effect(command: list[str], *args: object, **kwargs: object) -> SandboxResult:
        if command[:2] == ["pipenv", "install"]:
            generated_lockfile.write_text("{}")
        return SandboxResult(exit_code=0, stdout="", stderr="")

    runner = MagicMock(side_effect=runner_side_effect)
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    node(state)

    assert not generated_lockfile.exists()


def test_node_keeps_preexisting_lockfile(state: BlackboardState) -> None:
    preexisting_lockfile = state.workspace_path / "poetry.lock"
    preexisting_lockfile.write_text("")
    runner = _ok_runner()
    node = make_env_installer_node(timeout=900, installer_runner=runner)

    node(state)

    assert preexisting_lockfile.exists()
