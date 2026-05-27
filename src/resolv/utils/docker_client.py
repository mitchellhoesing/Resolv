"""Docker-py wrappers for sandboxed command execution.

`run_in_sandbox` mounts the per-issue workspace into a disposable container,
runs the command with bounded CPU/memory, captures stdout/stderr, and
removes the container afterward. Timeouts kill the container.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

from resolv.exceptions import SandboxError


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str


def get_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise SandboxError(f"Docker daemon unreachable: {exc}") from exc


def run_in_sandbox(
    command: list[str],
    workspace_path: Path,
    *,
    image_tag: str,
    timeout: int = 600,
    network: str = "none",
    memory_limit: str = "2g",
    cpu_count: float = 2.0,
) -> SandboxResult:
    client = get_client()
    container: Container | None = None
    try:
        try:
            container = client.containers.run(
                image=image_tag,
                command=command,
                volumes={str(workspace_path.resolve()): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                network_mode=network,
                mem_limit=memory_limit,
                nano_cpus=int(cpu_count * 1_000_000_000),
                detach=True,
                stdout=True,
                stderr=True,
            )
        except ImageNotFound as exc:
            raise SandboxError(f"Sandbox image {image_tag!r} is not built: {exc}") from exc

        try:
            wait_result = container.wait(timeout=timeout)
        except Exception as exc:
            container.kill()
            raise SandboxError(f"Sandbox timed out after {timeout}s: {exc}") from exc

        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        return SandboxResult(
            exit_code=int(wait_result.get("StatusCode", -1)),
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except NotFound:
                pass
