"""Typer-based CLI entrypoint for Resolv.

Example:

    resolv run --repo octocat/Hello-World --issue 1
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from resolv.adapters.github_client import GitHubClient
from resolv.config import get_settings
from resolv.core.app import build_production_graph
from resolv.core.state import BlackboardState
from resolv.exceptions import ResolvError

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def _main() -> None:
    """Resolv — autonomous issue-to-PR pipeline."""


@app.command()
def run(
    repo: str = typer.Option(..., "--repo", help="Target repository as owner/name."),
    issue: int = typer.Option(..., "--issue", help="Issue number to resolve."),
    workspace_root: Path = typer.Option(
        Path("/workspace"),
        "--workspace-root",
        help="Directory under which per-issue workspaces are created (in-container default).",
    ),
) -> None:
    """Run the autonomous issue-to-PR pipeline for a single issue."""
    if "/" not in repo:
        typer.echo("error: --repo must be in 'owner/name' form", err=True)
        raise typer.Exit(2)
    owner, name = repo.split("/", 1)

    settings = get_settings()
    github_client = GitHubClient(settings.github_token)
    issue_ref = github_client.fetch_issue(owner, name, issue)

    workspace_path = workspace_root / f"{owner}__{name}__issue-{issue}"
    initial_state = BlackboardState(issue=issue_ref, workspace_path=workspace_path)

    graph = build_production_graph(settings)
    try:
        final_state = graph.invoke(initial_state)
    except ResolvError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if final_state.get("test_status") == "PASSED":
        typer.echo(final_state.get("test_output") or "PR opened")
        raise typer.Exit(0)
    typer.echo(
        f"Loop did not converge after {final_state.get('iteration', 0)} iterations "
        f"(test={final_state.get('test_status')})",
        err=True,
    )
    raise typer.Exit(1)


if __name__ == "__main__":
    sys.exit(app())
