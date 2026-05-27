"""CodeRabbit QA node — runs the CLI in the sandbox and parses findings.

Phase 2 stub: always approves. Real subprocess controller lands in Phase 4.
"""

from __future__ import annotations

from typing import Any

from resolv.core.state import BlackboardState


def coderabbit_qa_node(state: BlackboardState) -> dict[str, Any]:
    return {"qa_status": "APPROVED", "qa_findings": []}
