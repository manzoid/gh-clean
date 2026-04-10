from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import List, Optional

from .github import GitHubClient, GitHubError


SAMPLE_CONFIG = """protected_branches:
  - main
  - staging
  - production
"""


class ConfigError(RuntimeError):
    """Raised when the gh-clean config is missing or invalid."""


@dataclass
class RepoConfig:
    protected_branches: List[str]


def parse_protected_branches_csv(value: str) -> List[str]:
    branches = [item.strip() for item in value.split(",") if item.strip()]
    if not branches:
        raise ConfigError(
            "empty --protected-branches value\n\nExample:\n\nmain,staging,production"
        )
    return branches


def parse_config_yaml(text: str) -> RepoConfig:
    protected: List[str] = []
    in_protected = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            in_protected = stripped == "protected_branches:"
            continue
        if in_protected and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                protected.append(value)

    if not protected:
        raise ConfigError(
            "missing or empty protected_branches in .gh-clean.yml\n\nSample config:\n\n"
            + SAMPLE_CONFIG
        )

    return RepoConfig(protected_branches=protected)


def load_repo_config(client: GitHubClient) -> RepoConfig:
    try:
        payload = client.api(f"repos/{client.repo}/contents/.gh-clean.yml")
    except GitHubError as exc:
        raise ConfigError(
            "missing required .gh-clean.yml in repository root\n\nSample config:\n\n"
            + SAMPLE_CONFIG
        ) from exc

    content = payload.get("content")
    encoding = payload.get("encoding")
    if not content or encoding != "base64":
        raise ConfigError(
            "unable to read .gh-clean.yml content\n\nSample config:\n\n"
            + SAMPLE_CONFIG
        )

    decoded = base64.b64decode(content).decode("utf-8")
    return parse_config_yaml(decoded)


def resolve_repo_config(
    client: GitHubClient,
    protected_branches_override: Optional[str] = None,
) -> RepoConfig:
    if protected_branches_override is not None:
        return RepoConfig(
            protected_branches=parse_protected_branches_csv(protected_branches_override)
        )
    return load_repo_config(client)
