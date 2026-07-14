"""Env Installer node — installs the target repo's dev/test dependencies.

Runs once, after the clone and before the coder/test loop. Dependencies are
installed into a per-repo venv that lives NEXT TO the workspace, never inside
it: the coder's retry cleanup (`git clean -fdx`) and deliver's `git add -A`
must never see it. The install needs network access (package indexes), so it
runs via `run_networked` — untrusted build hooks are contained by the scrubbed
environment rather than a network namespace.

Detection is two-tier: an exclusive first-match manager tier (poetry, uv,
pipenv — each forced into our venv via environment variables, never config
mutation), then an additive pip tier combining editable installs and
requirements files into a single pip command. pytest is seeded into the venv
before target deps so a repo's own pin wins while guaranteeing the venv's
pytest can see the venv's site-packages.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from resolv.core.state import BlackboardState
from resolv.exceptions import InstallError
from resolv.utils.run_log import log_event
from resolv.utils.sandbox import run_networked

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_OUTPUT_TAIL_CHARS = 4000

# Lockfiles a manager-tier install may generate; anything not present before
# the install is removed afterwards so deliver's `git add -A` cannot commit it.
_LOCKFILE_NAMES = ("poetry.lock", "uv.lock", "Pipfile.lock")

_REQUIREMENTS_FILE_NAMES = (
    "requirements.txt",
    "requirements-dev.txt",
    "dev-requirements.txt",
    "requirements-test.txt",
    "test-requirements.txt",
)

# Optional-dependency extras that carry test tooling, in canonical order.
_TEST_EXTRA_NAMES = ("dev", "test", "tests", "testing")


@dataclass(frozen=True)
class InstallStep:
    command: list[str]
    label: str
    extra_env: dict[str, str] = field(default_factory=dict)


def venv_path_for(workspace_path: Path) -> Path:
    """Convention: the per-repo venv is a sibling of the workspace."""
    return workspace_path.parent / f"{workspace_path.name}__venv"


def detect_install_plan(workspace: Path, venv: Path) -> list[InstallStep]:
    """Map the workspace's dependency manifests to install steps.

    Manager tier (exclusive, first match wins): poetry → uv → pipenv. Managers
    are not translated to pip because pip's PEP 517 path drops their dev/test
    groups. Pip tier (fallthrough, additive): editable install + every
    requirements file, combined into one pip command. Empty list means no
    manifests were found (a stdlib-only repo is valid).
    """
    pyproject = workspace / "pyproject.toml"
    pyproject_text = ""
    if pyproject.is_file():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pyproject_text = ""

    if (workspace / "poetry.lock").is_file() or "[tool.poetry]" in pyproject_text:
        return [
            InstallStep(
                command=["poetry", "install", "--no-interaction"],
                label="poetry install",
                extra_env={"POETRY_VIRTUALENVS_CREATE": "false"},
            )
        ]
    if (workspace / "uv.lock").is_file():
        return [
            InstallStep(
                command=["uv", "sync", "--frozen"],
                label="uv sync",
                extra_env={"UV_PROJECT_ENVIRONMENT": str(venv)},
            )
        ]
    if (workspace / "Pipfile.lock").is_file():
        return [InstallStep(command=["pipenv", "sync", "--dev"], label="pipenv sync")]
    if (workspace / "Pipfile").is_file():
        return [InstallStep(command=["pipenv", "install", "--dev"], label="pipenv install")]

    pip_args: list[str] = []
    project_table = _parse_project_table(pyproject_text)
    if project_table is not None:
        extras = [
            extra_name
            for extra_name in _TEST_EXTRA_NAMES
            if extra_name in project_table.get("optional-dependencies", {})
        ]
        target = f".[{','.join(extras)}]" if extras else "."
        pip_args.extend(["-e", target])
    elif (workspace / "setup.py").is_file() or (workspace / "setup.cfg").is_file():
        pip_args.extend(["-e", "."])
    for file_name in _REQUIREMENTS_FILE_NAMES:
        if (workspace / file_name).is_file():
            pip_args.extend(["-r", file_name])
    requirements_dir = workspace / "requirements"
    if requirements_dir.is_dir():
        for requirements_file in sorted(requirements_dir.glob("*.txt")):
            pip_args.extend(["-r", f"requirements/{requirements_file.name}"])

    if pip_args:
        return [
            InstallStep(
                command=[f"{venv}/bin/python", "-m", "pip", "install", *pip_args],
                label="pip install",
            )
        ]
    return []


def make_env_installer_node(
    *,
    timeout: int,
    installer_runner: Callable[..., Any] = run_networked,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def env_installer_node(state: BlackboardState) -> dict[str, Any]:
        workspace = state.workspace_path
        venv = venv_path_for(workspace)

        if (venv / "bin" / "python").exists():
            log_event("[env_installer] venv already present")
        else:
            log_event(f"[env_installer] creating venv at {venv}")
            _run_step(
                InstallStep(
                    command=[sys.executable, "-m", "venv", str(venv)],
                    label="venv creation",
                ),
                workspace,
                timeout=timeout,
                installer_runner=installer_runner,
                venv_path=None,
            )
        _run_step(
            InstallStep(
                command=[f"{venv}/bin/python", "-m", "pip", "install", "pytest"],
                label="pytest seed",
            ),
            workspace,
            timeout=timeout,
            installer_runner=installer_runner,
            venv_path=venv,
        )

        plan = detect_install_plan(workspace, venv)
        if not plan:
            log_event("[env_installer] no dependency manifests detected; proceeding")
        preexisting_lockfiles = {
            lockfile_name
            for lockfile_name in _LOCKFILE_NAMES
            if (workspace / lockfile_name).is_file()
        }
        for step in plan:
            _run_step(
                step,
                workspace,
                timeout=timeout,
                installer_runner=installer_runner,
                venv_path=venv,
            )
        _remove_generated_lockfiles(workspace, preexisting_lockfiles)
        return {}

    return env_installer_node


def _run_step(
    step: InstallStep,
    workspace: Path,
    *,
    timeout: int,
    installer_runner: Callable[..., Any],
    venv_path: Path | None,
) -> None:
    log_event(f"[env_installer] running: {' '.join(step.command)}")
    result = installer_runner(
        step.command,
        workspace,
        timeout=timeout,
        venv_path=venv_path,
        extra_env=step.extra_env,
    )
    if result.exit_code != 0:
        output_tail = (result.stdout + result.stderr)[-_OUTPUT_TAIL_CHARS:]
        log_event(f"[env_installer] error: {step.label} failed (exit {result.exit_code})")
        raise InstallError(
            f"{step.label} failed (exit {result.exit_code}): "
            f"{' '.join(step.command)}\n{output_tail}"
        )


def _parse_project_table(pyproject_text: str) -> dict[str, Any] | None:
    if not pyproject_text:
        return None
    try:
        parsed = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return None
    project_table = parsed.get("project")
    return project_table if isinstance(project_table, dict) else None


def _remove_generated_lockfiles(workspace: Path, preexisting: set[str]) -> None:
    for lockfile_name in _LOCKFILE_NAMES:
        lockfile = workspace / lockfile_name
        if lockfile_name not in preexisting and lockfile.is_file():
            lockfile.unlink()
            log_event(f"[env_installer] removed generated lockfile {lockfile_name}")
