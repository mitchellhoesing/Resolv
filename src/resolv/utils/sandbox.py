"""In-process isolation for running an untrusted repo's test suite.

Resolv itself runs inside the per-issue container as the trusted root process.
The target repo's test command is untrusted, so it is spawned as a child with
two controls applied directly, rather than trusting a shell to manage them:

  * Network namespacing — the child is launched under `unshare --net`, which
    detaches it into a fresh, unconfigured network namespace. Loopback is
    brought up (many suites bind localhost) but there is no external route, so
    a hallucinated or malicious test cannot reach the network or exfiltrate.
  * Environment scrubbing — the child receives an explicitly constructed env
    containing only baseline system variables. Secrets (API keys, tokens) and
    every RESOLV_* setting are omitted entirely, never merely unset later.

`unshare --net` needs CAP_SYS_ADMIN, so the container must be run with
`--cap-add=SYS_ADMIN`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from resolv.exceptions import SandboxError

# Baseline variables the test process legitimately needs. Everything else —
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
) -> SandboxResult:
    """Run ``command`` in ``workspace_path`` with no network and scrubbed env.

    Returns the captured exit code and output. A timeout is reported as a
    failed run (non-zero exit) rather than raising, so the loop can feed it
    back to the coder. Raises SandboxError only when the isolation tooling
    itself is missing.
    """
    isolated_command = ["unshare", "--net", "--", "/bin/sh", "-c", _NETNS_WRAPPER, *command]
    try:
        completed = subprocess.run(
            isolated_command,
            cwd=str(workspace_path),
            env=_scrubbed_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SandboxError(
            "isolation tooling unavailable (need 'unshare' and a Linux container "
            f"run with --cap-add=SYS_ADMIN): {exc}"
        ) from exc
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
            stderr=f"test run timed out after {timeout}s",
        )
    return SandboxResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _scrubbed_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
