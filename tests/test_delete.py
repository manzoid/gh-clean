import unittest
from unittest import mock

from gh_clean.delete import delete_branches
from gh_clean.report import BranchReport, ReportResult


def branch(
    name: str,
    recommendation: str,
    lifecycle: str = "merged",
    warnings=None,
    vetoes=None,
    excluded_reasons=None,
    tip_sha: str = "sha",
):
    return BranchReport(
        name=name,
        tip_sha=tip_sha,
        excluded_reasons=excluded_reasons or [],
        protection_status="known",
        role="has-head-prs",
        lifecycle=lifecycle,
        vetoes=vetoes or [],
        warnings=warnings or [],
        recommendation=recommendation,
        observed_at="2026-04-09T22:00:00+00:00",
    )


def report(*branches: BranchReport) -> ReportResult:
    return ReportResult(
        repo="owner/repo",
        default_branch="main",
        observed_at="2026-04-09T22:00:00+00:00",
        complete=True,
        global_warnings=[],
        branches=list(branches),
    )


class DeleteTests(unittest.TestCase):
    @mock.patch("gh_clean.delete.generate_report")
    def test_skips_review_branch_without_override(self, mock_generate_report):
        mock_generate_report.return_value = report(
            branch(
                "feature/merged-drift",
                recommendation="review",
                lifecycle="merged",
                warnings=["tip-differs-from-merged-head:3"],
                tip_sha="new-sha",
            )
        )

        run = delete_branches(
            repo="owner/repo",
            branch_names=["feature/merged-drift"],
            input_report_path=None,
            recommendation=None,
            extra_excludes=[],
            dry_run=True,
            force_merged_tip_mismatch=False,
            allow_tip_change=False,
        )
        self.assertEqual(run.results[0].status, "skipped")

    @mock.patch("gh_clean.delete.generate_report")
    def test_allows_tip_mismatch_override(self, mock_generate_report):
        mock_generate_report.return_value = report(
            branch(
                "feature/merged-drift",
                recommendation="review",
                lifecycle="merged",
                warnings=["tip-differs-from-merged-head:3"],
                tip_sha="new-sha",
            )
        )

        run = delete_branches(
            repo="owner/repo",
            branch_names=["feature/merged-drift"],
            input_report_path=None,
            recommendation=None,
            extra_excludes=[],
            dry_run=True,
            force_merged_tip_mismatch=True,
            allow_tip_change=False,
        )
        self.assertEqual(run.results[0].status, "would-delete")

    @mock.patch("gh_clean.delete.generate_report")
    @mock.patch("gh_clean.delete.load_report")
    def test_skips_when_tip_changed_since_input(self, mock_load_report, mock_generate_report):
        mock_load_report.return_value = report(branch("feature/a", recommendation="delete-candidate", tip_sha="old"))
        mock_generate_report.return_value = report(branch("feature/a", recommendation="delete-candidate", tip_sha="new"))

        run = delete_branches(
            repo="owner/repo",
            branch_names=[],
            input_report_path="/tmp/report.json",
            recommendation="delete-candidate",
            extra_excludes=[],
            dry_run=True,
            force_merged_tip_mismatch=False,
            allow_tip_change=False,
        )
        self.assertEqual(run.results[0].status, "skipped")
        self.assertIn("tip changed", run.results[0].reason)


if __name__ == "__main__":
    unittest.main()
