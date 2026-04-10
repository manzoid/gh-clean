from __future__ import annotations

import datetime as dt
import fnmatch
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .config import resolve_repo_config
from .github import GitHubClient, GitHubError


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def qualify_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def max_pr_number(prs: Iterable[Dict[str, Any]]) -> Optional[int]:
    numbers = [pr["number"] for pr in prs]
    return max(numbers) if numbers else None


def parallel_map_dict(items: Iterable[str], fn, max_workers: int = 12) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(fn, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            results[item] = future.result()
    return results


@dataclass
class BranchReport:
    name: str
    tip_sha: str
    excluded_reasons: List[str]
    protection_status: str
    role: str
    lifecycle: str
    vetoes: List[str]
    warnings: List[str]
    recommendation: str
    observed_at: str
    head_prs: List[int] = field(default_factory=list)
    base_prs: List[int] = field(default_factory=list)
    tip_commit_date: Optional[str] = None
    tip_commit_author: Optional[str] = None
    tip_commit_committer: Optional[str] = None
    most_recent_head_pr_number: Optional[int] = None
    most_recent_head_pr_state: Optional[str] = None
    most_recent_base_pr_number: Optional[int] = None
    most_recent_open_head_pr_is_draft: Optional[bool] = None


@dataclass
class ReportResult:
    repo: str
    default_branch: str
    observed_at: str
    complete: bool
    global_warnings: List[str]
    branches: List[BranchReport]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "default_branch": self.default_branch,
            "observed_at": self.observed_at,
            "complete": self.complete,
            "global_warnings": self.global_warnings,
            "branches": [asdict(branch) for branch in self.branches],
        }


def match_ruleset_branch(ruleset: Dict[str, Any], repo_name: str, branch: str) -> bool:
    if ruleset.get("enforcement") not in {"active", "evaluate"}:
        return False
    if ruleset.get("target") != "branch":
        return False

    conditions = ruleset.get("conditions", {})
    repo_cond = conditions.get("repository_name")
    if repo_cond:
        included = repo_cond.get("include") or []
        excluded = repo_cond.get("exclude") or []
        if included and repo_name not in included:
            return False
        if repo_name in excluded:
            return False

    ref_cond = conditions.get("ref_name") or {}
    include = ref_cond.get("include") or []
    exclude = ref_cond.get("exclude") or []
    qualified = qualify_ref(branch)

    included = True if not include else any(fnmatch.fnmatchcase(qualified, pat) for pat in include)
    excluded = any(fnmatch.fnmatchcase(qualified, pat) for pat in exclude)
    return included and not excluded


def recommendation_for(
    excluded_reasons: List[str],
    protection_status: str,
    hard_veto_base_open: bool,
    lifecycle: str,
    soft_tip_mismatch: bool,
) -> str:
    if excluded_reasons:
        return "blocked"
    if protection_status == "unknown":
        return "blocked"
    if hard_veto_base_open:
        return "blocked"
    if lifecycle == "active":
        return "keep"
    if lifecycle == "merged" and soft_tip_mismatch:
        return "review"
    if lifecycle == "merged":
        return "delete-candidate"
    if lifecycle == "integrated":
        return "delete-candidate"
    if lifecycle == "closed-unmerged":
        return "review"
    if lifecycle == "base-only-stale-candidate":
        return "review"
    if lifecycle == "untracked":
        return "review"
    return "review"


def classify_branch(
    *,
    repo_name: str,
    default_branch: str,
    branch: Dict[str, Any],
    commit: Dict[str, Any],
    rulesets: List[Dict[str, Any]],
    configured_protected_branches: List[str],
    head_prs: List[Dict[str, Any]],
    base_prs: List[Dict[str, Any]],
    compare_status: Optional[str],
    base_branch_compare_status: Optional[str],
    observed_at: str,
) -> BranchReport:
    name = branch["name"]
    sha = branch["commit"]["sha"]
    commit_author = (commit.get("commit", {}).get("author") or {}).get("name")
    commit_date = (commit.get("commit", {}).get("author") or {}).get("date")
    commit_committer = (commit.get("commit", {}).get("committer") or {}).get("name")

    matched_rulesets = [
        ruleset["name"] for ruleset in rulesets if match_ruleset_branch(ruleset, repo_name, name)
    ]

    excluded_reasons: List[str] = []
    protection_status = "known"
    warnings: List[str] = []
    vetoes: List[str] = []

    if name == default_branch:
        excluded_reasons.append("default-branch")
    if name in configured_protected_branches:
        excluded_reasons.append("config-protected-branch")
    if matched_rulesets:
        excluded_reasons.extend([f"ruleset:{name_}" for name_ in matched_rulesets])
    if branch.get("protected") and not matched_rulesets and name != default_branch:
        excluded_reasons.append("branch-protected")

    if head_prs:
        role = "has-head-prs"
    elif base_prs:
        role = "base-only"
    else:
        role = "no-pr-involvement"

    open_head = [pr for pr in head_prs if pr["state"] == "open"]
    merged_head = [pr for pr in head_prs if pr.get("merged_at")]
    closed_unmerged = [pr for pr in head_prs if pr["state"] == "closed" and not pr.get("merged_at")]
    open_base = [pr for pr in base_prs if pr["state"] == "open"]

    if open_head:
        lifecycle = "active"
    elif merged_head:
        lifecycle = "merged"
    elif closed_unmerged:
        lifecycle = "closed-unmerged"
    elif role == "base-only":
        if compare_status in {"behind", "identical"} and not open_base:
            lifecycle = "integrated"
        else:
            lifecycle = "base-only-stale-candidate"
    else:
        lifecycle = "untracked"

    if open_base:
        for pr in open_base:
            vetoes.append(f"base-of-open-pr:{pr['number']}")

    soft_tip_mismatch = False
    if lifecycle == "merged":
        latest_merged = max(merged_head, key=lambda pr: pr["merged_at"])
        merge_time_sha = latest_merged.get("merge_time_head_oid") or latest_merged["head"]["sha"]
        if merge_time_sha != sha:
            soft_tip_mismatch = True
            warnings.append(f"tip-differs-from-merged-head:{latest_merged['number']}")
        merged_base = latest_merged["base"]["ref"]
        if merged_base != default_branch and base_branch_compare_status not in {None, "behind", "identical"}:
            warnings.append(f"merged-into-non-default-base-not-contained:{merged_base}")

    if lifecycle == "closed-unmerged":
        latest_closed = max(closed_unmerged, key=lambda pr: pr["closed_at"] or "")
        closed_at = latest_closed.get("closed_at")
        if closed_at and commit_date and commit_date > closed_at:
            warnings.append("tip-newer-than-pr-close")

    most_recent_head = max(head_prs, key=lambda pr: pr.get("closed_at") or pr.get("updated_at") or "") if head_prs else None
    most_recent_open_head = max(open_head, key=lambda pr: pr.get("updated_at") or pr.get("created_at") or "") if open_head else None
    most_recent_base = max(base_prs, key=lambda pr: pr.get("closed_at") or pr.get("updated_at") or "") if base_prs else None

    recommendation = recommendation_for(
        excluded_reasons=excluded_reasons,
        protection_status=protection_status,
        hard_veto_base_open=bool(open_base),
        lifecycle=lifecycle,
        soft_tip_mismatch=soft_tip_mismatch,
    )
    if lifecycle == "merged" and any(
        warning.startswith("merged-into-non-default-base-not-contained:") for warning in warnings
    ):
        recommendation = "review"

    return BranchReport(
        name=name,
        tip_sha=sha,
        excluded_reasons=excluded_reasons,
        protection_status=protection_status,
        role=role,
        lifecycle=lifecycle,
        vetoes=vetoes,
        warnings=warnings,
        recommendation=recommendation,
        observed_at=observed_at,
        head_prs=[pr["number"] for pr in head_prs],
        base_prs=[pr["number"] for pr in base_prs],
        tip_commit_date=commit_date,
        tip_commit_author=commit_author,
        tip_commit_committer=commit_committer,
        most_recent_head_pr_number=most_recent_head["number"] if most_recent_head else None,
        most_recent_head_pr_state=(
            "MERGED"
            if most_recent_head and most_recent_head.get("merged_at")
            else most_recent_head["state"].upper() if most_recent_head else None
        ),
        most_recent_base_pr_number=most_recent_base["number"] if most_recent_base else None,
        most_recent_open_head_pr_is_draft=most_recent_open_head.get("draft") if most_recent_open_head else None,
    )


def generate_report(
    repo: str,
    extra_excludes: Optional[List[str]] = None,
    protected_branches_override: Optional[str] = None,
) -> ReportResult:
    client = GitHubClient(repo)
    observed_at = utc_now_iso()

    repo_meta = client.get_repo()
    repo_config = resolve_repo_config(
        client,
        protected_branches_override=protected_branches_override,
    )
    default_branch = repo_meta["default_branch"]
    branches = client.get_branches()
    open_pulls = client.get_pulls(state="open")
    open_head_refs = {
        pr["head"]["ref"]
        for pr in open_pulls
        if (((pr.get("head") or {}).get("repo") or {}).get("full_name") == repo)
    }
    needs_closed_scan = any(branch["name"] not in open_head_refs for branch in branches)
    closed_pulls = client.get_pulls(state="closed") if needs_closed_scan else []
    pulls = open_pulls + closed_pulls
    merged_numbers = [pr["number"] for pr in pulls if pr.get("merged_at")]
    merged_head_oids = client.get_pull_head_oids(merged_numbers)
    ruleset_summaries = client.get_ruleset_summaries()
    rulesets = [client.get_ruleset_detail(summary) for summary in ruleset_summaries]
    configured_protected_branches = sorted(set(repo_config.protected_branches + (extra_excludes or [])))

    matched_rulesets_by_branch = {
        branch["name"]: [
            ruleset["name"]
            for ruleset in rulesets
            if match_ruleset_branch(ruleset, repo_meta["name"], branch["name"])
        ]
        for branch in branches
    }

    branch_commits: Dict[str, Dict[str, Any]] = {}
    unique_shas = sorted({branch["commit"]["sha"] for branch in branches})
    branch_commits = parallel_map_dict(unique_shas, client.get_commit, max_workers=12)

    head_prs_by_branch: Dict[str, List[Dict[str, Any]]] = {}
    base_prs_by_branch: Dict[str, List[Dict[str, Any]]] = {}

    for pr in pulls:
        if pr.get("merged_at"):
            pr["merge_time_head_oid"] = merged_head_oids.get(pr["number"]) or pr["head"]["sha"]
        head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
        if head_repo == repo:
            head_prs_by_branch.setdefault(pr["head"]["ref"], []).append(pr)
        base_prs_by_branch.setdefault(pr["base"]["ref"], []).append(pr)

    reports: List[BranchReport] = []
    global_warnings: List[str] = []
    branches_needing_compare = set()
    for name in base_prs_by_branch:
        if (
            name != default_branch
            and name not in configured_protected_branches
            and not matched_rulesets_by_branch.get(name)
        ):
            branches_needing_compare.add(name)
    for prs in head_prs_by_branch.values():
        merged = [pr for pr in prs if pr.get("merged_at")]
        if merged:
            latest_merged = max(merged, key=lambda pr: pr["merged_at"])
            merged_base = latest_merged["base"]["ref"]
            if (
                merged_base != default_branch
                and merged_base not in configured_protected_branches
                and not matched_rulesets_by_branch.get(merged_base)
            ):
                branches_needing_compare.add(merged_base)
    compare_status_by_branch: Dict[str, Optional[str]] = {}
    if branches_needing_compare:
        with ThreadPoolExecutor(max_workers=12) as executor:
            future_to_branch = {
                executor.submit(client.compare, default_branch, name): name
                for name in sorted(branches_needing_compare)
            }
            for future in as_completed(future_to_branch):
                name = future_to_branch[future]
                try:
                    compare_status_by_branch[name] = future.result()["status"]
                except GitHubError as exc:
                    compare_status_by_branch[name] = None
                    global_warnings.append(f"compare-failed:{name}:{exc}")

    for branch in branches:
        name = branch["name"]
        role_base_only = name not in head_prs_by_branch and name in base_prs_by_branch

        compare_status: Optional[str] = None
        if role_base_only and not any(pr["state"] == "open" for pr in base_prs_by_branch.get(name, [])):
            compare_status = compare_status_by_branch.get(name)

        reports.append(
            classify_branch(
                repo_name=repo_meta["name"],
                default_branch=default_branch,
                branch=branch,
                commit=branch_commits[branch["commit"]["sha"]],
                rulesets=rulesets,
                configured_protected_branches=configured_protected_branches,
                head_prs=head_prs_by_branch.get(name, []),
                base_prs=base_prs_by_branch.get(name, []),
                compare_status=compare_status,
                base_branch_compare_status=(
                    compare_status_by_branch.get(
                        max(
                            [pr for pr in head_prs_by_branch.get(name, []) if pr.get("merged_at")],
                            key=lambda pr: pr["merged_at"],
                        )["base"]["ref"]
                    )
                    if any(pr.get("merged_at") for pr in head_prs_by_branch.get(name, []))
                    else None
                ),
                observed_at=observed_at,
            )
        )

    order = {"blocked": 0, "review": 1, "delete-candidate": 2, "keep": 3}
    reports.sort(key=lambda item: (order.get(item.recommendation, 99), item.name))
    return ReportResult(
        repo=repo,
        default_branch=default_branch,
        observed_at=observed_at,
        complete=not global_warnings,
        global_warnings=global_warnings,
        branches=reports,
    )


def load_report(path: str) -> ReportResult:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return ReportResult(
        repo=data["repo"],
        default_branch=data["default_branch"],
        observed_at=data["observed_at"],
        complete=data["complete"],
        global_warnings=list(data.get("global_warnings", [])),
        branches=[BranchReport(**branch) for branch in data["branches"]],
    )


def format_table(report: ReportResult) -> str:
    rows: List[List[str]] = []
    headers = ["branch", "recommendation", "lifecycle", "role", "notes"]

    for branch in report.branches:
        notes = branch.excluded_reasons + branch.vetoes + branch.warnings
        rows.append(
            [
                branch.name,
                branch.recommendation,
                branch.lifecycle,
                branch.role,
                ", ".join(notes),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def fmt(row: List[str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    output = [fmt(headers), fmt(["-" * width for width in widths])]
    output.extend(fmt(row) for row in rows)
    return "\n".join(output)


def format_json(report: ReportResult) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)
