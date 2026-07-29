"""Production wiring: turn a Settings instance into a compiled LangGraph application."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from resolv.adapters.claude_code_client import ClaudeCodeBackend, ClaudeCodeClient
from resolv.adapters.github_client import GitHubClient
from resolv.config import Settings, get_settings
from resolv.core.graph import NodeFn, build_graph, sqlite_checkpointer
from resolv.core.state import BlackboardState
from resolv.nodes.coder import make_coder_node
from resolv.nodes.context_broker import make_context_broker_node
from resolv.nodes.deliver import make_deliver_node
from resolv.nodes.env_installer import make_env_installer_node
from resolv.nodes.test_runner import agent_test_report, make_test_runner_node
from resolv.utils.run_log import log_directory, log_event

CHECKPOINT_DATABASE_NAME = "checkpoints.sqlite"


def checkpoint_database_path() -> Path:
    """Where a run's state history is written, alongside its log files."""
    return log_directory() / CHECKPOINT_DATABASE_NAME


def log_node_boundaries(node_name: str, node_fn: NodeFn) -> NodeFn:
    """Wrap a node so the run log records the state it received and the keys it wrote.

    Wrapping at the wiring layer keeps the node modules themselves untouched and
    leaves stub-wired test graphs free of logging.
    """

    def logged_node(state: BlackboardState) -> dict[str, Any]:
        log_event(f"[{node_name}] enter {state.summary()}")
        update = node_fn(state)
        written_keys = ", ".join(sorted(update)) if update else "(no changes)"
        log_event(f"[{node_name}] exit wrote {written_keys}")
        return update

    return logged_node


def build_production_graph(settings: Settings | None = None) -> CompiledStateGraph:
    settings = settings or get_settings()
    # The coder agent runs the suite itself through the same sandboxed path the
    # test_runner node uses; wiring it here keeps `adapters` free of any import
    # from `nodes`.
    coder_backend = ClaudeCodeBackend(
        ClaudeCodeClient(),
        model=settings.coder.claude_model,
        run_suite=partial(
            agent_test_report, timeout=settings.sandbox.test_timeout_seconds
        ),
        max_turns=settings.coder.max_turns,
        anthropic_api_key=settings.anthropic_api_key,
    )
    github_client = GitHubClient(settings.github_token)

    return build_graph(
        context_broker_fn=log_node_boundaries(
            "context_broker",
            make_context_broker_node(github_token=settings.github_token),
        ),
        env_installer_fn=log_node_boundaries(
            "env_installer",
            make_env_installer_node(
                timeout=settings.sandbox.install_timeout_seconds,
            ),
        ),
        coder_fn=log_node_boundaries("coder", make_coder_node(coder_backend)),
        test_runner_fn=log_node_boundaries(
            "test_runner",
            make_test_runner_node(timeout=settings.sandbox.test_timeout_seconds),
        ),
        deliver_fn=log_node_boundaries(
            "deliver",
            make_deliver_node(
                github_client=github_client,
                base_branch=settings.delivery.base_branch,
                branch_prefix=settings.delivery.branch_prefix,
            ),
        ),
        max_iterations=settings.loop.max_iterations,
        checkpointer=sqlite_checkpointer(checkpoint_database_path()),
    )
