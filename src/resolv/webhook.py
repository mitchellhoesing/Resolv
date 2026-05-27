"""GitHub webhook listener.

A factory-built FastAPI app verifies HMAC signatures, filters events
to actionable issues (`issues.opened` and `issue_comment.created`
matching the trigger phrase), and enqueues an `(owner, repo, number)`
tuple onto an in-process `asyncio.Queue`. A single background worker
consumes the queue and drives `build_production_graph` to completion.

Run with: `uvicorn --factory resolv.webhook:create_app`
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Header, HTTPException, Request

from resolv.adapters.github_client import GitHubClient
from resolv.config import Settings, get_settings
from resolv.core.app import build_production_graph
from resolv.core.state import BlackboardState

logger = logging.getLogger(__name__)

WorkItem = tuple[str, str, int]
Runner = Callable[[WorkItem], Awaitable[None]]


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def should_process(
    event: str | None, payload: dict[str, Any], trigger_phrase: str
) -> bool:
    if event == "issues" and payload.get("action") == "opened":
        return True
    if event == "issue_comment" and payload.get("action") == "created":
        body = (payload.get("comment") or {}).get("body", "")
        return trigger_phrase.lower() in body.lower()
    return False


def _extract_work_item(payload: dict[str, Any]) -> WorkItem:
    issue = payload["issue"]
    repo = payload["repository"]
    return (repo["owner"]["login"], repo["name"], issue["number"])


def _default_runner(settings: Settings, workspace_root: Path) -> Runner:
    async def run(item: WorkItem) -> None:
        owner, repo, number = item
        github = GitHubClient(settings.github_token)
        issue_ref = github.fetch_issue(owner, repo, number)
        workspace = workspace_root / f"{owner}__{repo}__issue-{number}"
        state = BlackboardState(issue=issue_ref, workspace_path=workspace)
        graph = build_production_graph(settings)
        await asyncio.to_thread(graph.invoke, state)

    return run


async def _worker_loop(queue: asyncio.Queue[WorkItem], runner: Runner) -> None:
    while True:
        item = await queue.get()
        try:
            await runner(item)
        except Exception:
            logger.exception("worker failed processing %s/%s#%d", *item)
        finally:
            queue.task_done()


def create_app(
    settings: Settings | None = None,
    *,
    runner: Runner | None = None,
    workspace_root: Path = Path("./workspaces"),
    start_worker: bool = True,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_runner = runner or _default_runner(resolved_settings, workspace_root)
    queue: asyncio.Queue[WorkItem] = asyncio.Queue()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task: asyncio.Task[None] | None = None
        if start_worker:
            task = asyncio.create_task(_worker_loop(queue, resolved_runner))
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(lifespan=lifespan)
    app.state.queue = queue
    app.state.settings = resolved_settings

    @app.post("/github")
    async def github_webhook(
        request: Request,
        x_github_event: str | None = Header(default=None),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, str]:
        body = await request.body()
        secret = resolved_settings.github_webhook_secret.get_secret_value()
        if not verify_signature(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        if not should_process(
            x_github_event, payload, resolved_settings.webhook.trigger_phrase
        ):
            return {"status": "ignored"}
        try:
            item = _extract_work_item(payload)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"missing field: {exc}") from exc
        await queue.put(item)
        return {"status": "queued"}

    return app
