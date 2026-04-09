## gh-clean test plan

### Purpose

This document defines how `gh-clean` will be validated before it is used
against real repositories for branch deletion.

The tool is safety-sensitive. A good test plan must do more than prove
that the CLI runs. It must prove that:

- branch classification is correct
- protection and veto handling are conservative
- GitHub API responses are interpreted correctly
- deletion re-validation prevents stale or unsafe actions
- live GitHub behavior matches the assumptions baked into the design

This document is a companion to
[design.md](/Users/timothymansfield/code/src/github.com/manzoid/gh-clean/docs/design.md).

## Testing principles

- Prefer deterministic tests over ad hoc live verification
- Keep the core decision engine pure and heavily unit tested
- Treat GitHub API parsing as a separate testable layer
- Use live integration tests to verify GitHub behavior, not to carry the
  whole correctness burden
- Test destructive behavior only in dedicated sandbox repositories
- Prefer false negatives in tests over permissive assumptions

## Test layers

The test strategy has five layers.

### 1. Decision-engine unit tests

These tests exercise the classification and recommendation logic without
any network or CLI concerns.

Inputs:

- repository metadata
- branch metadata
- PR summaries
- protection state
- ruleset matches
- compare / containment results
- merge-time SHA results

Outputs:

- role classification
- lifecycle assessment
- vetoes
- warnings
- final recommendation

These should be table-driven tests and should form the largest part of
the suite.

### 2. Ruleset evaluation tests

Ruleset logic is safety-critical enough to deserve a dedicated test
layer.

These tests should validate:

- exact ref matches
- include-pattern matching
- exclude-pattern matching
- multiple matching rulesets
- active vs disabled rulesets
- inherited rulesets from parent scopes
- incomplete ruleset data leading to `protection unknown`

If this layer is wrong, the tool can incorrectly recommend deleting a
protected branch.

### 3. GitHub API translation tests

These tests verify that GitHub REST and GraphQL responses are translated
into the internal model correctly.

They should use recorded fixtures or hand-curated response samples.

This layer should cover:

- repository metadata
- branch listing pagination
- PR listing pagination
- head/base PR matching
- fork PR filtering by repository identity
- ruleset listing via `includes_parents=true`
- compare API results
- missing permissions
- rate-limit responses
- partial responses and error handling
- merged PR `headRefOid`
- merged PR REST `head.sha`

### 4. CLI report tests

These tests validate the user-facing report behavior once the decision
engine and API translation layers are working.

They should cover:

- terminal report rendering
- grouping and sorting
- filters
- JSON output shape
- incomplete-run warnings
- stable recommendation output

JSON tests should assert contract stability. Terminal output tests may
use snapshots, but snapshots alone are not sufficient.

### 5. Live integration tests

These tests run against real GitHub repositories and validate that the
tool behaves correctly against live API behavior.

They should be few in number, carefully scoped, and run only against
dedicated sandbox repositories.

These tests exist to catch:

- API behavior that differs from documentation
- auth/permission edge cases
- ruleset inheritance behavior
- branch deletion semantics
- live time-of-check / time-of-use races

Live integration tests should never be the only proof of correctness.

## Required test categories

The following scenarios must be covered before calling the tool safe for
real use.

### Core classification scenarios

- branch with at least one open head PR => `active`, recommendation
  `keep`
- branch with merged head PR and no tip mismatch => `merged`,
  recommendation `delete-candidate`
- branch with merged head PR and tip mismatch => `merged`,
  recommendation `review`
- branch with only closed-unmerged head PRs => `closed-unmerged`,
  recommendation `review`
- branch with no head PRs and no base PRs => `untracked`,
  recommendation `review`
- branch with no head PRs, incoming PRs, and tip contained in default =>
  `integrated`, recommendation `delete-candidate`
- branch with no head PRs, incoming PRs, and tip not contained in
  default => `base-only-stale-candidate`, recommendation `review`

### Hard-veto scenarios

- default branch => `blocked`
- branch excluded by user config => `blocked`
- branch matched by active repo ruleset => `blocked`
- branch matched by inherited org ruleset => `blocked`
- branch with unknown protection status => `blocked`
- branch that is base of an open PR => `blocked`

### Matching and join scenarios

- fork PR with same head branch name as a local branch must not match
- multiple PRs from the same branch must respect lifecycle priority order
- base PR matching must use base ref correctly
- deleted fork head repositories must not produce false matches

### Staleness-signal scenarios

- no-PR branch newer than stale threshold => still `review`
- no-PR branch older than stale threshold => still `review`
- closed-unmerged branch with tip newer than most recent PR close =>
  `review` with rework signal
- stale draft PR branch => still `keep`, but surfaced as stale-active

### Delete re-validation scenarios

- branch disappears between report and delete => skipped, not fatal
- branch tip changes between report and delete => skipped unless override
- branch becomes protected after report => skipped
- branch becomes base of open PR after report => skipped
- merged-tip mismatch override deletes only when explicitly requested
- default branch and protected branches remain undeletable even with
  overrides

### Partial and failure scenarios

- ruleset endpoint unavailable => incomplete report, blocked deletions
- compare API error => affected branch downgraded to `review`
- PR pagination incomplete => run marked partial
- rate limit exceeded mid-run => partial results clearly flagged

## Recommended implementation shape for testing

The codebase should be structured so the main logic is easy to test
without network access.

Recommended layers:

1. `internal/model`
2. `internal/classify`
3. `internal/rulesets`
4. `internal/githubapi`
5. `internal/report`
6. `cmd/gh-clean`

Key rule:

- `internal/classify` should depend only on internal data structures, not
  on `gh`, HTTP clients, or CLI formatting

This separation is what makes the heavy unit-test strategy feasible.

## Fixtures

### Fixture types

The test suite should maintain reusable fixtures for:

- branch inventories
- PR inventories
- ruleset payloads
- branch protection payloads
- compare API responses
- GraphQL merged-PR responses
- error responses such as 403, 404, and rate-limit cases

### Fixture style

Prefer small, purpose-built fixtures over giant raw captures.

Each fixture should support one clear scenario. If a live API response is
captured, it should be reduced to the minimal relevant fields before it
becomes a long-term fixture.

### Golden outputs

For report tests, use golden JSON outputs and optionally golden terminal
output snapshots.

Golden files are useful only when paired with targeted assertions about
recommendations and vetoes.

## Live test environments

### Real-world read-only target

`SakanaAIBusiness/marlin` is a good real-world report target because it
is an internal/private repo with real branches, PRs, and rulesets.

Use it for:

- validating report generation against realistic data volume
- validating ruleset reads on a private/internal repo
- spotting classification surprises in a real team repo

Do not use it as the first target for destructive tests.

### Sandbox repo

A dedicated sandbox repository is required for delete testing.

This repo should be disposable and should contain intentionally-created
branches and PRs covering the major lifecycle states.

Minimum scenarios to build in the sandbox repo:

- default branch `main`
- branch matched by repo-level ruleset
- branch with open head PR
- branch with merged head PR
- branch with closed-unmerged head PR
- base-only branch with closed incoming PRs
- base of open PR
- no-PR branch
- branch reused across multiple PRs
- merged branch with branch-tip drift after merge

### Sandbox organization

If available, a dedicated sandbox organization is the preferred live test
environment.

Benefits:

- validates inherited org rulesets
- allows repo-level and org-level protections to layer
- avoids risking real production repositories
- enables end-to-end delete tests with realistic permissions

The sandbox org should contain:

- one primary test repository for branch lifecycle tests
- org-level rulesets targeting at least `main` and one pattern such as
  `release/*`
- optionally a second repo later if cross-repo comparison becomes useful

### Current sandbox inventory

The current live sandbox baseline is:

- org: `gh-clean-sandbox`
- repo: `gh-clean-sandbox/sandbox`

Current rulesets:

- org ruleset: `Protect main and release branches`
  - targets `main`
  - targets `release/*`
- repo ruleset: `Protect production branch`
  - targets `production`

Current branch inventory:

- `main`
  - protected by inherited org ruleset
- `production`
  - protected by repo ruleset
- `release/v1`
  - protected by inherited org ruleset
- `feature/open-pr`
  - open head PR to `main`
- `feature/merged-clean`
  - merged head PR to `main`
- `feature/merged-drift`
  - merged head PR to `main`, then advanced with an extra commit after
    merge
- `feature/closed-unmerged`
  - closed-without-merge head PR to `main`, then advanced with another
    commit after close
- `integration/base-open`
  - base of an open PR from `feature/depends-on-base`
- `integration/base-integrated`
  - no head PRs, incoming merged PR, and tip contained in `main`
- `integration/base-stale`
  - no head PRs, incoming merged PR, and tip not contained in `main`
- `no-pr/orphan`
  - no matching PRs as head or base
- `feature/reused-history`
  - one closed-without-merge head PR followed by one merged head PR

Current PR inventory:

- `#1` open
  - `feature/open-pr -> main`
- `#2` merged
  - `feature/merged-clean -> main`
- `#3` merged
  - `feature/merged-drift -> main`
- `#4` closed without merge
  - `feature/closed-unmerged -> main`
- `#5` open
  - `feature/depends-on-base -> integration/base-open`
- `#6` merged
  - `feature/into-base-integrated -> integration/base-integrated`
- `#7` merged
  - `feature/into-base-stale -> integration/base-stale`
- `#8` closed without merge
  - `feature/reused-history -> main`
- `#9` merged
  - `feature/reused-history -> main`

Validated special cases:

- `integration/base-integrated` compares as contained in `main`
- `integration/base-stale` compares as not fully contained in `main`
- PR `#3` records merge-time head SHA
  `32dbb4fe49fab15ab9d42512a625f4332eaa2fa6`
- current branch `feature/merged-drift` points to
  `c02b54e9e473e3a3363d38cc712dd8b2b6446f8c`
- therefore `feature/merged-drift` is a live merged-tip-mismatch case

This inventory should be treated as the reference live fixture for early
manual validation of the report command.

## Suggested live test scenarios

These scenarios should be automated where practical, but may begin as a
manual validation checklist.

### Scenario 1: merged branch safe to delete

1. Create branch `feature/merged-clean`
2. Open PR to `main`
3. Merge PR
4. Leave branch unchanged
5. Confirm report marks branch `delete-candidate`
6. Run delete dry-run
7. Run delete for real
8. Confirm audit output records branch name and SHA

### Scenario 2: merged branch with tip drift

1. Create branch `feature/merged-drift`
2. Open PR to `main`
3. Merge PR
4. Push another commit to the same branch
5. Confirm report marks branch `review`, not `delete-candidate`
6. Confirm delete skips without explicit override
7. Confirm override path works only when requested

### Scenario 3: base of open PR

1. Create branch `integration/test-base`
2. Open PR from another branch into `integration/test-base`
3. Confirm report marks `integration/test-base` as `blocked`
4. Confirm delete skips it even if otherwise stale

### Scenario 4: inherited org ruleset

1. Create org ruleset targeting `main`
2. Create repo in sandbox org
3. Confirm repo rulesets endpoint with `includes_parents=true` surfaces
   the inherited ruleset
4. Confirm report marks `main` as protected without querying org
   rulesets directly

### Scenario 5: report/delete race

1. Generate report for a candidate branch
2. Change the branch state before delete
3. Run delete
4. Confirm delete re-validation skips safely and explains why

## Manual verification checklist

Before first real use on a non-sandbox repository:

1. Run report only
2. Inspect all `blocked` branches and confirm they make sense
3. Inspect a sample of `review` branches from each lifecycle category
4. Inspect at least a few `delete-candidate` branches manually in GitHub
5. Run delete in `--dry-run`
6. Confirm audit output format is usable for recovery
7. Delete only a small explicit set first

This checklist is not a substitute for automated tests. It is a final
sanity check before real-world use.

## Exit criteria

The tool should not be considered ready for general use until:

- core decision-engine tests cover all recommendation rules
- ruleset matching has dedicated tests
- GitHub API translation is tested with fixtures
- JSON report output has contract tests
- live sandbox tests have exercised at least one successful delete and
  one safe skip for each major veto path
- the tool has been run in report-only mode against at least one real
  non-sandbox repository

## Open testing questions

- Should live integration tests be runnable in CI, or only manually?
- Do we want to record live GitHub fixtures automatically, or hand-curate
  them?
- Should the sandbox repo state be managed by setup scripts so tests can
  recreate it from scratch?

These are execution questions, not reasons to delay writing the core
testable architecture.
