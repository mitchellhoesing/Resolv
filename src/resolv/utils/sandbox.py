"""In-process isolation for running an untrusted repo's test suite and installs.

Resolv itself runs inside the per-issue container as the trusted root process.
Two kinds of untrusted child commands are spawned here:

  * Test runs (`run_isolated`) — launched under `unshare --net`, which detaches
    the child into a fresh, unconfigured network namespace. Loopback is brought
    up (many suites bind localhost) but there is no external route, so a
    hallucinated or malicious test cannot reach the network or exfiltrate.
  * Dependency installs (`run_networked`) — pip/poetry/uv need the network to
    reach package indexes, so no netns is applied. Installs still execute
    untrusted code (setup.py, build hooks); environment scrubbing is the
    control there.

Both paths receive an explicitly constructed env containing only baseline
system variables. Secrets (API keys, tokens) and every RESOLV_* setting are
omitted entirely, never merely unset later. When a per-repo venv is supplied,
its bin directory is prepended to PATH (image binaries remain as fallback) and
VIRTUAL_ENV is set.

`unshare --net` needs CAP_SYS_ADMIN, so the container must be run with
`--cap-add=SYS_ADMIN`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from resolv.exceptions import SandboxError

# Baseline variables the child process legitimately needs. Everything else —
# crucially anthropic/openai/github secrets and RESOLV_* config — is dropped.
_SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TERM")

# Bring loopback up inside the new netns, then exec the real command. "$0"/"$@"
# carry the test argv so no shell quoting is applied to it.
_NETNS_WRAPPER = 'ip link set lo up 2>/dev/null; exec "$0" "$@"'


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str


def run_isolated(
    command: list[str],
    workspace_path: Path,
    *,
    timeout: int,
    venv_path: Path | None = None,
) -> SandboxResult:
    """Run ``command`` in ``workspace_path`` with no network and scrubbed env.

    Returns the captured exit code and output. A timeout is reported as a
    failed run (non-zero exit) rather than raising, so the loop can feed it
    back to the coder. Raises SandboxError only when the isolation tooling
    itself is missing.
    """
    isolated_command = ["unshare", "--net", "--", "/bin/sh", "-c", _NETNS_WRAPPER, *command]
    env = _scrubbed_env()
    if venv_path is not None:
        env = _apply_venv(env, venv_path)
    return _execute(
        isolated_command,
        workspace_path,
        timeout=timeout,
        env=env,
        missing_tool_hint=(
            "isolation tooling unavailable (need 'unshare' and a Linux container "
            "run with --cap-add=SYS_ADMIN)"
        ),
    )


def run_networked(
    command: list[str],
    workspace_path: Path,
    *,
    timeout: int,
    venv_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> SandboxResult:
    """Run ``command`` in ``workspace_path`` with network but scrubbed env.

    Used for dependency installation, which must reach package indexes and so
    cannot run inside the network namespace. Same timeout and exception
    semantics as `run_isolated`.
    """
    env = _scrubbed_env()
    if venv_path is not None:
        env = _apply_venv(env, venv_path)
    if extra_env:
        env.update(extra_env)
    return _execute(
        command,
        workspace_path,
        timeout=timeout,
        env=env,
        missing_tool_hint="install tooling unavailable",
    )


def _execute(
    command: list[str],
    workspace_path: Path,
    *,
    timeout: int,
    env: dict[str, str],
    missing_tool_hint: str,
) -> SandboxResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SandboxError(f"{missing_tool_hint}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raw_output = exc.stdout
        partial: str = (
            raw_output.decode("utf-8", errors="replace")
            if isinstance(raw_output, bytes)
            else (raw_output or "")
        )
        return SandboxResult(
            exit_code=-1,
            stdout=partial,
            stderr=f"command timed out after {timeout}s",
        )
    return SandboxResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _apply_venv(env: dict[str, str], venv_path: Path) -> dict[str, str]:
    venv_bin = f"{venv_path}/bin"
    updated = dict(env)
    existing_path = updated.get("PATH")
    updated["PATH"] = f"{venv_bin}:{existing_path}" if existing_path else venv_bin
    updated["VIRTUAL_ENV"] = str(venv_path)
    return updated


def _scrubbed_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
