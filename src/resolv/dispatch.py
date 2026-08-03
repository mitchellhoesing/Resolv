"""Launching a disposable per-issue container that runs the pipeline.

Shared by the webhook worker and the `resolv dispatch` CLI command so both
paths build the identical `docker run` invocation.

Secrets are passed through by name (`-e NAME`, no value) so they reach the
container's env without appearing in the host process's argv. The container
fetches the issue, clones, codes, tests, and pushes — the host only launches
it. CAP_SYS_ADMIN is required for the in-container test isolation.

The container is `--rm`, so its log files would die with it; the host log
directory is bind-mounted over the container's so a finished run stays
diagnosable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from resolv.config import Settings

# The image's WORKDIR is /workspace and run_log writes to `logs/` relative to
# cwd, so the container's log directory is /workspace/logs. Per-issue workspaces
# live alongside it as /workspace/<owner>__<repo>__issue-<n>, so there's no clash.
_CONTAINER_LOG_DIRECTORY = "/workspace/logs"


def host_log_directory(owner: str, repo: str, number: int) -> Path:
    """Host directory bind-mounted onto one issue's container log directory.

    One directory per issue: run_log names files per minute and its entries
    carry no run identity, so a shared directory would interleave consecutive
    issues into the same files with no way to tell them apart. The name matches
    the per-issue workspace convention.
    """
    return Path("logs").resolve() / f"{owner}__{repo}__issue-{number}"


def build_dispatch_command(
    settings: Settings,
    owner: str,
    repo: str,
    number: int,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Build the `docker run` argv for one issue. Secret values never appear here."""
    resolv_argv = ["run", "--repo", f"{owner}/{repo}", "--issue", str(number)]
    if dry_run:
        resolv_argv.append("--dry-run")
    return [
        "docker", "run", "--rm", "--cap-add=SYS_ADMIN",
        "-e", "RESOLV_GITHUB_TOKEN",
        "-e", "RESOLV_ANTHROPIC_API_KEY",
        "-e", "CLAUDE_CODE_OAUTH_TOKEN",
        "-v", f"{host_log_directory(owner, repo, number)}:{_CONTAINER_LOG_DIRECTORY}",
        settings.sandbox.image_tag,
        *resolv_argv,
    ]


def dispatch_issue(
    settings: Settings,
    owner: str,
    repo: str,
    number: int,
    *,
    dry_run: bool = False,
) -> int:
    """Run the per-issue container to completion and return its exit code."""
    # Docker would create the mount source as root-owned if it were missing.
    host_log_directory(owner, repo, number).mkdir(parents=True, exist_ok=True)
    command = build_dispatch_command(settings, owner, repo, number, dry_run=dry_run)
    env = {
        **os.environ,
        "RESOLV_GITHUB_TOKEN": settings.github_token.get_secret_value(),
        "RESOLV_ANTHROPIC_API_KEY": settings.anthropic_api_key.get_secret_value(),
        "CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token.get_secret_value(),
    }
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode
