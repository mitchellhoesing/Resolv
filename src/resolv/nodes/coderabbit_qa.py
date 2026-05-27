"""CodeRabbit QA node — runs the CLI in the sandbox and parses findings."""

from __future__ import annotations

from typing import Any, Callable

from resolv.core.state import BlackboardState
from resolv.utils.docker_client import run_in_sandbox


def make_coderabbit_qa_node(
    *,
    image_tag: str,
    timeout: int,
    sandbox_runner: Callable[..., Any] = run_in_sandbox,
) -> Callable[[BlackboardState], dict[str, Any]]:
    def coderabbit_qa_node(state: BlackboardState) -> dict[str, Any]:
        result = sandbox_runner(
            ["coderabbit", "review", "--plain"],
            state.workspace_path,
            image_tag=image_tag,
            timeout=timeout,
            network="bridge",
        )
        findings = [line for line in result.stdout.splitlines() if line.strip()]
        if result.exit_code == 0 and not findings:
            return {"qa_status": "APPROVED", "qa_findings": []}
        if not findings and result.stderr.strip():
            findings = [result.stderr.strip()]
        return {"qa_status": "REJECTED", "qa_findings": findings}

    return coderabbit_qa_node
