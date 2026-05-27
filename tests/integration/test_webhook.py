"""Integration tests for the FastAPI webhook listener."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from pydantic import SecretStr

from resolv.config import Settings
from resolv.webhook import create_app, should_process, verify_signature

SECRET = "shhh"


def _signed_headers(body: bytes, event: str) -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def _settings() -> Settings:
    return Settings(
        github_token=SecretStr("ghp_fake"),
        github_webhook_secret=SecretStr(SECRET),
    )


def _issue_payload(action: str = "opened", number: int = 7) -> dict:
    return {
        "action": action,
        "issue": {"number": number, "title": "x", "body": ""},
        "repository": {"name": "widgets", "owner": {"login": "acme"}},
    }


def _comment_payload(comment_body: str, number: int = 11) -> dict:
    return {
        "action": "created",
        "comment": {"body": comment_body},
        "issue": {"number": number, "title": "x", "body": ""},
        "repository": {"name": "widgets", "owner": {"login": "acme"}},
    }


def test_verify_signature_accepts_valid_and_rejects_invalid() -> None:
    body = b"{}"
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(SECRET, body, f"sha256={digest}") is True
    assert verify_signature(SECRET, body, "sha256=deadbeef") is False
    assert verify_signature(SECRET, body, None) is False
    assert verify_signature(SECRET, body, "md5=foo") is False


def test_should_process_routes_events() -> None:
    assert should_process("issues", {"action": "opened"}, "/resolv fix") is True
    assert should_process("issues", {"action": "closed"}, "/resolv fix") is False
    assert (
        should_process(
            "issue_comment",
            {"action": "created", "comment": {"body": "please /resolv fix this"}},
            "/resolv fix",
        )
        is True
    )
    assert (
        should_process(
            "issue_comment",
            {"action": "created", "comment": {"body": "thanks"}},
            "/resolv fix",
        )
        is False
    )
    assert should_process("push", {}, "/resolv fix") is False


def test_post_without_signature_returns_401() -> None:
    app = create_app(_settings(), start_worker=False)
    with TestClient(app) as client:
        response = client.post("/github", json=_issue_payload())
    assert response.status_code == 401


def test_post_with_invalid_signature_returns_401() -> None:
    app = create_app(_settings(), start_worker=False)
    with TestClient(app) as client:
        response = client.post(
            "/github",
            content=b"{}",
            headers={
                "X-Hub-Signature-256": "sha256=deadbeef",
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401


def test_valid_issue_opened_is_queued() -> None:
    app = create_app(_settings(), start_worker=False)
    payload = _issue_payload(number=42)
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        response = client.post("/github", content=body, headers=_signed_headers(body, "issues"))
    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert app.state.queue.get_nowait() == ("acme", "widgets", 42)


def test_comment_with_trigger_phrase_is_queued() -> None:
    app = create_app(_settings(), start_worker=False)
    payload = _comment_payload("please /resolv fix this", number=11)
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        response = client.post(
            "/github", content=body, headers=_signed_headers(body, "issue_comment")
        )
    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert app.state.queue.get_nowait() == ("acme", "widgets", 11)


def test_comment_without_trigger_phrase_is_ignored() -> None:
    app = create_app(_settings(), start_worker=False)
    payload = _comment_payload("thanks!", number=11)
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        response = client.post(
            "/github", content=body, headers=_signed_headers(body, "issue_comment")
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert app.state.queue.empty()


def test_unsupported_event_is_ignored() -> None:
    app = create_app(_settings(), start_worker=False)
    payload = {"action": "synchronize"}
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        response = client.post(
            "/github", content=body, headers=_signed_headers(body, "pull_request")
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


def test_worker_consumes_queue_and_invokes_runner() -> None:
    seen: list = []
    done = asyncio.Event()

    async def runner(item):
        seen.append(item)
        done.set()

    app = create_app(_settings(), runner=runner, start_worker=True)
    payload = _issue_payload(number=1)
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        response = client.post("/github", content=body, headers=_signed_headers(body, "issues"))
        assert response.status_code == 200

        # Drain: the worker is on the same event loop, so wait briefly for it.
        async def wait_for_done():
            await asyncio.wait_for(done.wait(), timeout=2.0)

        asyncio.run(wait_for_done())

    assert seen == [("acme", "widgets", 1)]
