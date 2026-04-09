import unittest

from gh_clean.config import ConfigError, parse_config_yaml
from gh_clean.report import classify_branch, match_ruleset_branch, recommendation_for


def make_branch(name: str, sha: str = "abc123", protected: bool = False):
    return {"name": name, "commit": {"sha": sha}, "protected": protected}


def make_commit(date: str = "2026-04-09T22:00:00Z"):
    return {
        "commit": {
            "author": {"name": "tester", "date": date},
            "committer": {"name": "tester", "date": date},
        }
    }


def make_pr(number: int, state: str, head: str, base: str, merged_at=None, closed_at=None, draft=False):
    return {
        "number": number,
        "state": state,
        "draft": draft,
        "head": {"ref": head, "sha": f"sha-{number}"},
        "base": {"ref": base},
        "merged_at": merged_at,
        "closed_at": closed_at,
        "updated_at": closed_at or merged_at or "2026-04-09T22:00:00Z",
        "created_at": "2026-04-09T21:00:00Z",
    }


class RecommendationTests(unittest.TestCase):
    def test_blocked_wins(self):
        self.assertEqual(recommendation_for(["default-branch"], "known", False, "merged", False), "blocked")

    def test_active_kept(self):
        self.assertEqual(recommendation_for([], "known", False, "active", False), "keep")

    def test_merged_tip_mismatch_is_review(self):
        self.assertEqual(recommendation_for([], "known", False, "merged", True), "review")

    def test_integrated_is_delete_candidate(self):
        self.assertEqual(recommendation_for([], "known", False, "integrated", False), "delete-candidate")


class RulesetMatchTests(unittest.TestCase):
    def test_ruleset_matches_release_pattern(self):
        ruleset = {
            "enforcement": "active",
            "target": "branch",
            "conditions": {"ref_name": {"include": ["refs/heads/release/*"], "exclude": []}},
        }
        self.assertTrue(match_ruleset_branch(ruleset, "sandbox", "release/v1"))
        self.assertFalse(match_ruleset_branch(ruleset, "sandbox", "feature/test"))

    def test_ruleset_respects_repository_name_condition(self):
        ruleset = {
            "enforcement": "active",
            "target": "branch",
            "conditions": {
                "repository_name": {"include": ["sandbox"], "exclude": [], "protected": False},
                "ref_name": {"include": ["refs/heads/main"], "exclude": []},
            },
        }
        self.assertTrue(match_ruleset_branch(ruleset, "sandbox", "main"))
        self.assertFalse(match_ruleset_branch(ruleset, "other", "main"))


class ClassificationTests(unittest.TestCase):
    def test_closed_unmerged_with_post_close_commit_has_warning(self):
        branch = make_branch("feature/closed")
        commit = make_commit(date="2026-04-09T22:10:00Z")
        pr = make_pr(
            4,
            "closed",
            "feature/closed",
            "main",
            merged_at=None,
            closed_at="2026-04-09T22:05:00Z",
        )
        report = classify_branch(
            repo_name="sandbox",
            default_branch="main",
            branch=branch,
            commit=commit,
            rulesets=[],
            configured_protected_branches=[],
            head_prs=[pr],
            base_prs=[],
            compare_status=None,
            base_branch_compare_status=None,
            observed_at="2026-04-09T22:20:00+00:00",
        )
        self.assertEqual(report.lifecycle, "closed-unmerged")
        self.assertEqual(report.recommendation, "review")
        self.assertIn("tip-newer-than-pr-close", report.warnings)

    def test_base_only_integrated_is_delete_candidate(self):
        report = classify_branch(
            repo_name="sandbox",
            default_branch="main",
            branch=make_branch("integration/base"),
            commit=make_commit(),
            rulesets=[],
            configured_protected_branches=[],
            head_prs=[],
            base_prs=[make_pr(6, "closed", "feature/x", "integration/base", merged_at="2026-04-09T22:00:00Z")],
            compare_status="behind",
            base_branch_compare_status=None,
            observed_at="2026-04-09T22:20:00+00:00",
        )
        self.assertEqual(report.role, "base-only")
        self.assertEqual(report.lifecycle, "integrated")
        self.assertEqual(report.recommendation, "delete-candidate")

    def test_open_head_pr_is_keep(self):
        report = classify_branch(
            repo_name="sandbox",
            default_branch="main",
            branch=make_branch("feature/open"),
            commit=make_commit(),
            rulesets=[],
            configured_protected_branches=[],
            head_prs=[make_pr(1, "open", "feature/open", "main")],
            base_prs=[],
            compare_status=None,
            base_branch_compare_status=None,
            observed_at="2026-04-09T22:20:00+00:00",
        )
        self.assertEqual(report.lifecycle, "active")
        self.assertEqual(report.recommendation, "keep")

    def test_merged_into_non_default_base_not_in_default_is_review(self):
        report = classify_branch(
            repo_name="sandbox",
            default_branch="main",
            branch=make_branch("feature/stacked"),
            commit=make_commit(),
            rulesets=[],
            configured_protected_branches=[],
            head_prs=[
                make_pr(
                    7,
                    "closed",
                    "feature/stacked",
                    "integration/base-stale",
                    merged_at="2026-04-09T22:10:00Z",
                    closed_at="2026-04-09T22:10:00Z",
                )
            ],
            base_prs=[],
            compare_status=None,
            base_branch_compare_status="ahead",
            observed_at="2026-04-09T22:20:00+00:00",
        )
        self.assertEqual(report.lifecycle, "merged")
        self.assertEqual(report.recommendation, "review")
        self.assertIn(
            "merged-into-non-default-base-not-contained:integration/base-stale",
            report.warnings,
        )


class ConfigTests(unittest.TestCase):
    def test_parse_config_yaml(self):
        config = parse_config_yaml("protected_branches:\n  - main\n  - production\n")
        self.assertEqual(config.protected_branches, ["main", "production"])

    def test_parse_config_yaml_rejects_empty(self):
        with self.assertRaises(ConfigError):
            parse_config_yaml("protected_branches:\n")


if __name__ == "__main__":
    unittest.main()
