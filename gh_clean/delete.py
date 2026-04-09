from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

from .github import GitHubClient
from .report import BranchReport, ReportResult, generate_report, load_report


@dataclass
class DeleteResult:
    branch: str
    status: str
    reason: str
    tip_sha: Optional[str]


@dataclass
class DeleteRun:
    repo: str
    observed_at: str
    dry_run: bool
    results: List[DeleteResult]

    def to_dict(self) -> Dict[str, object]:
        return {
            "repo": self.repo,
            "observed_at": self.observed_at,
            "dry_run": self.dry_run,
            "results": [asdict(result) for result in self.results],
        }


def _index_branches(report: ReportResult) -> Dict[str, BranchReport]:
    return {branch.name: branch for branch in report.branches}


def _selected_branch_names(
    *,
    branch_names: Sequence[str],
    input_report: Optional[ReportResult],
    recommendation: Optional[str],
) -> List[str]:
    names = list(branch_names)
    if input_report and recommendation:
        names.extend(branch.name for branch in input_report.branches if branch.recommendation == recommendation)
    elif input_report and not branch_names:
        names.extend(branch.name for branch in input_report.branches)
    return sorted(set(names))


def delete_branches(
    *,
    repo: str,
    branch_names: Sequence[str],
    input_report_path: Optional[str],
    recommendation: Optional[str],
    extra_excludes: Optional[Sequence[str]],
    dry_run: bool,
    force_merged_tip_mismatch: bool,
    allow_tip_change: bool,
) -> DeleteRun:
    prior_report = load_report(input_report_path) if input_report_path else None
    live_report = generate_report(repo, extra_excludes=list(extra_excludes or []))
    live_by_name = _index_branches(live_report)
    prior_by_name = _index_branches(prior_report) if prior_report else {}
    selected = _selected_branch_names(
        branch_names=branch_names,
        input_report=prior_report,
        recommendation=recommendation,
    )

    if not selected:
        raise ValueError("delete requires at least one selected branch")

    client = GitHubClient(repo)
    results: List[DeleteResult] = []

    for name in selected:
        prior = prior_by_name.get(name)
        live = live_by_name.get(name)

        if live is None:
            results.append(DeleteResult(branch=name, status="skipped", reason="branch no longer exists", tip_sha=None))
            continue

        if prior and prior.tip_sha != live.tip_sha and not allow_tip_change:
            results.append(
                DeleteResult(
                    branch=name,
                    status="skipped",
                    reason="branch tip changed since input report",
                    tip_sha=live.tip_sha,
                )
            )
            continue

        if live.recommendation == "blocked":
            results.append(
                DeleteResult(
                    branch=name,
                    status="skipped",
                    reason="blocked by current report state",
                    tip_sha=live.tip_sha,
                )
            )
            continue

        if live.recommendation == "keep":
            results.append(
                DeleteResult(
                    branch=name,
                    status="skipped",
                    reason="branch is currently active",
                    tip_sha=live.tip_sha,
                )
            )
            continue

        if live.recommendation == "review":
            only_tip_mismatch = (
                live.lifecycle == "merged"
                and live.warnings
                and all(warning.startswith("tip-differs-from-merged-head:") for warning in live.warnings)
                and not live.vetoes
                and not live.excluded_reasons
            )
            if not (force_merged_tip_mismatch and only_tip_mismatch):
                results.append(
                    DeleteResult(
                        branch=name,
                        status="skipped",
                        reason="branch requires review",
                        tip_sha=live.tip_sha,
                    )
                )
                continue

        if dry_run:
            results.append(
                DeleteResult(
                    branch=name,
                    status="would-delete",
                    reason="eligible after re-validation",
                    tip_sha=live.tip_sha,
                )
            )
            continue

        encoded = quote(f"heads/{name}", safe="")
        client.api_delete(f"repos/{repo}/git/refs/{encoded}")
        results.append(
            DeleteResult(
                branch=name,
                status="deleted",
                reason="deleted after re-validation",
                tip_sha=live.tip_sha,
            )
        )

    return DeleteRun(repo=repo, observed_at=live_report.observed_at, dry_run=dry_run, results=results)


def format_delete_json(run: DeleteRun) -> str:
    return json.dumps(run.to_dict(), indent=2, sort_keys=True)


def format_delete_table(run: DeleteRun) -> str:
    rows = [["branch", "status", "tip_sha", "reason"]]
    for result in run.results:
        rows.append([result.branch, result.status, result.tip_sha or "", result.reason])

    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    formatted = []
    for idx, row in enumerate(rows):
        formatted.append("  ".join(value.ljust(widths[col]) for col, value in enumerate(row)))
        if idx == 0:
            formatted.append("  ".join("-" * width for width in widths))
    return "\n".join(formatted)
