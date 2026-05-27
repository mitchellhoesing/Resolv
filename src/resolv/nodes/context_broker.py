"""Context Broker node — ingestion, indexing, and pruning.

Phase 2 stub: returns no context. Real implementation lands in Phase 4.
"""

from __future__ import annotations

from typing import Any

from resolv.core.state import BlackboardState


def context_broker_node(state: BlackboardState) -> dict[str, Any]:
    return {"pruned_context": [], "scip_index_path": None}
