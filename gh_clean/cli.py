from __future__ import annotations

import argparse
import sys

from .config import ConfigError, SAMPLE_CONFIG
from .delete import delete_branches, format_delete_json, format_delete_table
from .github import GitHubError, ensure_gh_authenticated, ensure_gh_available
from .report import format_json, format_table, generate_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gh-clean")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="Generate a cleanup report")
    report.add_argument("--repo", required=True, help="Repository in OWNER/REPO form")
    report.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )
    report.add_argument(
        "--protected-branches",
        help=(
            "Comma-delimited protected branches override, for example "
            "'main,staging,production'. When set, .gh-clean.yml is not required."
        ),
    )
    report.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional protected branch name to exclude",
    )

    delete = subparsers.add_parser("delete", help="Delete branches after re-validation")
    delete.add_argument("--repo", required=True, help="Repository in OWNER/REPO form")
    delete.add_argument("--branch", action="append", default=[], help="Branch name to delete")
    delete.add_argument(
        "--protected-branches",
        help=(
            "Comma-delimited protected branches override, for example "
            "'main,staging,production'. When set, .gh-clean.yml is not required."
        ),
    )
    delete.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional protected branch name to exclude",
    )
    delete.add_argument("--input", help="Path to a prior JSON report")
    delete.add_argument(
        "--recommendation",
        choices=["blocked", "review", "delete-candidate", "keep"],
        help="Select branches from the input report by recommendation",
    )
    delete.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    delete.add_argument(
        "--force-merged-tip-mismatch",
        action="store_true",
        help="Allow deletion of merged branches that only fail the tip mismatch soft veto",
    )
    delete.add_argument(
        "--allow-tip-change",
        action="store_true",
        help="Allow deletion when the branch tip changed since the input report",
    )
    delete.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )
    return parser


def _maybe_print_config_hint(args: argparse.Namespace) -> None:
    if getattr(args, "protected_branches", None):
        return
    print(
        "Hint: pass --protected-branches main,staging,production to override the repo config "
        "for this run.\n",
        file=sys.stderr,
    )
    print("Sample config:\n", file=sys.stderr)
    print(SAMPLE_CONFIG, file=sys.stderr, end="")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        ensure_gh_available()
        ensure_gh_authenticated()
        if args.command == "report":
            report = generate_report(
                args.repo,
                extra_excludes=args.exclude,
                protected_branches_override=args.protected_branches,
            )
            if args.format == "json":
                print(format_json(report))
            else:
                print(format_table(report))
            return 0

        if args.command == "delete":
            run = delete_branches(
                repo=args.repo,
                branch_names=args.branch,
                input_report_path=args.input,
                recommendation=args.recommendation,
                extra_excludes=args.exclude,
                protected_branches_override=args.protected_branches,
                dry_run=args.dry_run,
                force_merged_tip_mismatch=args.force_merged_tip_mismatch,
                allow_tip_change=args.allow_tip_change,
            )
            if args.format == "json":
                print(format_delete_json(run))
            else:
                print(format_delete_table(run))
            return 0
    except GitHubError as exc:
        print(f"gh-clean: GitHub API error: {exc}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"gh-clean: {exc}", file=sys.stderr)
        _maybe_print_config_hint(args)
        return 2
    except ValueError as exc:
        print(f"gh-clean: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2
