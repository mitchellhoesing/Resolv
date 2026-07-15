"""Launching a disposable per-issue container that runs the pipeline.

Shared by the webhook worker and the `resolv dispatch` CLI command so both
paths build the identical `docker run` invocation.

Secrets are passed through by name (`-e NAME`, no value) so they reach the
container's env without appearing in the host process's argv. The container
fetches the issue, clones, codes, tests, and pushes — the host only launches
it. CAP_SYS_ADMIN is required for the in-container test isolation.
"""

from __future__ import annotations

import os
import subprocess

from resolv.config import Settings


def build_dispatch_command(
    settings: Settings,
    owner: str,
    repo: str,
    number: int,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Build the `docker run` argv for one issue. Secret values never appear here."""
    command = [
        "docker", "run", "--rm", "--cap-add=SYS_ADMIN",
        "-e", "RESOLV_GITHUB_TOKEN",
        "-e", "RESOLV_ANTHROPIC_API_KEY",
        settings.sandbox.image_tag,
        "run", "--repo", f"{owner}/{repo}", "--issue", str(number),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def dispatch_issue(
    settings: Settings,
    owner: str,
    repo: str,
    number: int,
    *,
    dry_run: bool = False,
) -> int:
    """Run the per-issue container to completion and return its exit code."""
    command = build_dispatch_command(settings, owner, repo, number, dry_run=dry_run)
    env = {
        **os.environ,
        "RESOLV_GITHUB_TOKEN": settings.github_token.get_secret_value(),
        "RESOLV_ANTHROPIC_API_KEY": settings.anthropic_api_key.get_secret_value(),
    }
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode
