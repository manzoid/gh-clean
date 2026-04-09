from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional


class GitHubError(RuntimeError):
    """Raised when gh api calls fail."""


def ensure_gh_available() -> None:
    if shutil.which("gh") is None:
        raise GitHubError(
            "GitHub CLI (`gh`) is required but was not found in PATH.\n"
            "Install `gh`, then run `gh auth login`."
        )


def ensure_gh_authenticated() -> None:
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitHubError(
            "GitHub CLI is not authenticated.\n"
            "Run `gh auth login` and then retry."
        )


class GitHubClient:
    def __init__(self, repo: str) -> None:
        ensure_gh_available()
        ensure_gh_authenticated()
        self.repo = repo
        self.owner, self.name = repo.split("/", 1)

    def api(self, path: str) -> Any:
        cmd = ["gh", "api", path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitHubError(proc.stderr.strip() or proc.stdout.strip())
        return json.loads(proc.stdout)

    def api_delete(self, path: str) -> None:
        cmd = ["gh", "api", "-X", "DELETE", path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitHubError(proc.stderr.strip() or proc.stdout.strip())

    def graphql(self, query: str) -> Any:
        cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitHubError(proc.stderr.strip() or proc.stdout.strip())
        return json.loads(proc.stdout)

    def paginate_rest(self, path: str, per_page: int = 100) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            data = self.api(f"{path}{separator}per_page={per_page}&page={page}")
            if not isinstance(data, list):
                raise GitHubError(f"Expected list response for {path}")
            results.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return results

    def get_repo(self) -> Dict[str, Any]:
        return self.api(f"repos/{self.repo}")

    def get_branches(self) -> List[Dict[str, Any]]:
        return self.paginate_rest(f"repos/{self.repo}/branches")

    def get_pulls(self, state: str = "all") -> List[Dict[str, Any]]:
        return self.paginate_rest(f"repos/{self.repo}/pulls?state={state}")

    def get_ruleset_summaries(self) -> List[Dict[str, Any]]:
        return self.api(f"repos/{self.repo}/rulesets?includes_parents=true")

    def get_ruleset_detail(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        href = summary["_links"]["self"]["href"]
        if href.startswith("https://api.github.com/"):
            href = href[len("https://api.github.com/") :]
        return self.api(href)

    def get_commit(self, sha: str) -> Dict[str, Any]:
        return self.api(f"repos/{self.repo}/commits/{sha}")

    def compare(self, base: str, head: str) -> Dict[str, Any]:
        return self.api(f"repos/{self.repo}/compare/{base}...{head}")

    def get_default_branch_head_oid(self) -> Optional[str]:
        query = (
            "query { repository(owner:\"%s\", name:\"%s\") { "
            "defaultBranchRef { target { ... on Commit { oid } } } } }"
            % (self.owner, self.name)
        )
        data = self.graphql(query)
        return (
            data.get("data", {})
            .get("repository", {})
            .get("defaultBranchRef", {})
            .get("target", {})
            .get("oid")
        )

    def get_pull_head_oids(self, numbers: List[int]) -> Dict[int, Optional[str]]:
        if not numbers:
            return {}

        result: Dict[int, Optional[str]] = {}
        batch_size = 20
        for start in range(0, len(numbers), batch_size):
            batch = numbers[start : start + batch_size]
            fields = []
            for number in batch:
                fields.append(f'pr_{number}: pullRequest(number: {number}) {{ number headRefOid }}')
            query = (
                "query { repository(owner:\"%s\", name:\"%s\") { %s } }"
                % (self.owner, self.name, " ".join(fields))
            )
            data = self.graphql(query)
            repo = data.get("data", {}).get("repository", {})
            for number in batch:
                node = repo.get(f"pr_{number}") or {}
                result[number] = node.get("headRefOid")
        return result
