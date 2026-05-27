"""Production wiring: turn a Settings instance into a compiled LangGraph application."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from resolv.adapters.coder import build_coder
from resolv.adapters.github_client import GitHubClient
from resolv.config import Settings, get_settings
from resolv.core.graph import build_graph
from resolv.nodes.coder import make_coder_node
from resolv.nodes.coderabbit_qa import make_coderabbit_qa_node
from resolv.nodes.context_broker import make_context_broker_node
from resolv.nodes.deliver import make_deliver_node
from resolv.nodes.test_runner import make_test_runner_node


def build_production_graph(settings: Settings | None = None) -> CompiledStateGraph:
    settings = settings or get_settings()
    coder_backend = build_coder(
        backend=settings.coder.backend,
        claude_model=settings.coder.claude_model,
        litellm_model=settings.coder.litellm_model,
        litellm_api_key=settings.openai_api_key,
    )
    github_client = GitHubClient(settings.github_token)

    return build_graph(
        context_broker_fn=make_context_broker_node(
            max_chunks=settings.context.max_chunks,
            github_token=settings.github_token,
        ),
        coder_fn=make_coder_node(coder_backend),
        coderabbit_qa_fn=make_coderabbit_qa_node(
            image_tag=settings.sandbox.image_tag,
            timeout=settings.sandbox.qa_timeout_seconds,
        ),
        test_runner_fn=make_test_runner_node(
            image_tag=settings.sandbox.image_tag,
            timeout=settings.sandbox.test_timeout_seconds,
        ),
        deliver_fn=make_deliver_node(
            github_client=github_client,
            base_branch=settings.delivery.base_branch,
            branch_prefix=settings.delivery.branch_prefix,
        ),
        max_iterations=settings.loop.max_iterations,
    )
