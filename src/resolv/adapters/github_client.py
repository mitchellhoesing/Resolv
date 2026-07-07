"""PyGithub wrapper for issue ingestion and PR opening."""

from __future__ import annotations

from github import Auth, Github
from pydantic import SecretStr

from resolv.core.state import IssueRef
from resolv.exceptions import DeliveryError, IngestionError


class GitHubClient:
    def __init__(self, token: SecretStr) -> None:
        if not token.get_secret_value():
            raise IngestionError("GITHUB_TOKEN is empty; cannot authenticate to GitHub.")
        self._client = Github(auth=Auth.Token(token.get_secret_value()))

    def fetch_issue(self, owner: str, repo: str, number: int) -> IssueRef:
        try:
            repository = self._client.get_repo(f"{owner}/{repo}")
            issue = repository.get_issue(number)
        except Exception as exc:
            raise IngestionError(f"Failed to fetch {owner}/{repo}#{number}: {exc}") from exc
        return IssueRef(
            owner=owner,
            repo=repo,
            number=number,
            title=issue.title,
            body=issue.body or "",
            labels=tuple(label.name for label in issue.labels),
        )

    def open_pull_request(
        self,
        owner: str,
        repo: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        try:
            repository = self._client.get_repo(f"{owner}/{repo}")
            pull_request = repository.create_pull(
                title=title, body=body, head=head_branch, base=base_branch
            )
        except Exception as exc:
            raise DeliveryError(
                f"Failed to open PR {owner}/{repo} {head_branch}->{base_branch}: {exc}"
            ) from exc
        return pull_request.html_url
