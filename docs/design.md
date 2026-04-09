## gh-clean design

### Summary

`gh-clean` is a GitHub-focused remote branch cleanup tool. It evaluates
branches using GitHub repository state rather than any contributor's
local checkout, produces a reviewable report, and optionally deletes
branches after re-validating that they are still safe to remove.

The tool is intentionally conservative. It should help teams clean up
hundreds or thousands of stale remote branches without surprising anyone,
and it should prefer "skip and explain" over "guess and delete."

### Status of this document

This document is intended to be an implementation spec for v1.

- Where it says **must**, the behavior is required
- Where it says **should**, the behavior is strongly preferred but may be
  adapted if implementation constraints demand it
- Where it says **may**, the behavior is optional

If implementation discovers a mismatch between this document and GitHub's
actual API behavior, the design must be updated before the tool silently
adopts a different safety model.

### Goals

- Identify cleanup candidates using GitHub as the source of truth
- Work without reference to local branches, worktrees, or local HEAD
- Produce a human-reviewable report before deletion
- Support machine-readable output for automation and follow-up tooling
- Re-verify branch state before deletion to avoid time-of-check /
  time-of-use mistakes
- Respect default branches, protected branches, rulesets, and explicit
  user exclusions
- Scale to large repositories without obviously wasteful query patterns

### Non-goals

- Cleaning up local branches
- Reconstructing every possible historical intent behind a branch
- Perfectly resolving all stacked-PR edge cases
- Re-implementing every detail of GitHub's internal rules engine when a
  simpler conservative approximation is safer
- Automatically deleting ambiguous no-PR branches without human review

### V1 scope decisions

To keep v1 usable and safe, the following decisions are fixed:

- v1 must support a human-readable terminal report and JSON output
- v1 must support report-driven deletion with re-validation
- v1 must fail closed when protection or ruleset status cannot be
  determined
- v1 must not require a local `git fetch` or any local ancestry analysis
- v1 must not auto-delete branches in ambiguous categories solely because
  they exceed the stale threshold
- v1 must treat archived repositories as report-only

## Product model

### Core idea

A remote branch should be evaluated from two perspectives:

1. **Role classification**: how the branch participates in pull requests
2. **Lifecycle assessment**: what GitHub state suggests about whether the
   branch is still needed

This keeps the model easier to reason about than a single flat list of
states.

### Why pull requests are central

For remote cleanup, pull requests are the strongest repository-native
signal of branch intent:

- a branch used as PR head has an explicit "what happened to this work?"
  trail
- a branch used as PR base may still be an active integration target even
  if it has no head PRs of its own
- a branch with no PR involvement is inherently ambiguous and must be
  judged mostly by staleness and exclusion rules

Unlike local cleanup, remote cleanup does not care about uncommitted
changes, checked-out branches, or local reflogs.

## User workflows

### Workflow 1: report

The report command scans a repository and produces a categorized list of
remote branches. It does not delete anything.

The report is the main decision-support surface. It should answer:

- why each branch is in its current category
- whether it is definitely blocked, probably safe, or needs review
- what information a human needs in order to decide

### Workflow 2: delete

The delete command removes branches only after re-validating current
state.

Deletion can be driven by:

- an explicit list of branch names
- a report artifact produced by a previous run
- a filter such as "delete report rows marked deletable"

The delete command must be best-effort rather than atomic. Remote branch
deletion is an API operation performed one branch at a time, and state
may change between attempts.

The delete command must never infer its own target set from the live
repository alone. It must require an explicit selector such as branch
names, a prior JSON report, or an explicit filter argument.

### Dry-run

Both workflows should support dry-run behavior:

- `report` is inherently a dry-run
- `delete --dry-run` performs the same re-validation as `delete` but
  emits what would be deleted without deleting anything

## Safety model

### Safety principles

- Exclude branches that are definitely not cleanup targets
- Separate branch classification from deletion vetoes
- Re-check current state before deletion
- Skip on uncertainty when safety-critical information is unavailable
- Leave an audit trail sufficient to recreate deleted refs if needed
- Prefer false negatives over false positives

### Branches excluded from consideration

The following branches must never be proposed for deletion:

1. The repository's configured default branch
2. Branches protected by classic branch protection rules
3. Branches matched by active GitHub rulesets, evaluated
   conservatively
4. Branches excluded by user configuration or command-line flags

If a branch matches more than one exclusion source, the report should
surface all matching reasons even though any one of them is sufficient to
block deletion.

### Ruleset evaluation policy

GitHub rulesets are more complex than simple name matching. For v1, the
tool should take a conservative approach:

- evaluate branch-name targeting patterns against each branch
- honor include and exclude patterns where they are visible via the API
- treat active or evaluating rulesets as protective
- ignore bypass actors for safety purposes
- if org-level or inherited rulesets cannot be read due to permission
  limits, treat protection status as **unknown** and block deletion

This may over-protect branches, which is acceptable. It must not
under-protect them.

If the API surface does not expose enough information to conservatively
evaluate a visible ruleset against a branch, the result for that branch
must be `protection unknown`.

### Ruleset API and permissions decision

For v1, `gh-clean` must read rulesets through the repository endpoint,
not by querying organization rulesets directly:

- `GET /repos/{owner}/{repo}/rulesets?includes_parents=true`

Reason:

- this endpoint returns repository rulesets and inherited higher-level
  rulesets that apply to the repository
- the endpoint is aligned with the product need, which is "what active
  rulesets apply to this repository?"
- it avoids requiring organization-admin access merely to discover active
  inherited rulesets for a repository

Verified behavior and docs support this design:

- GitHub's repository ruleset API supports `includes_parents`, which
  includes higher-level rulesets that apply to the repository
- GitHub docs state that anyone with read access to a repository can view
  the active rulesets operating on that repository
- the direct organization ruleset endpoints require stronger
  organization-level administration permissions and are therefore the
  wrong dependency for repository cleanup scanning

Permission model for v1:

- with classic `gh auth` tokens, repository read access is sufficient for
  public repository ruleset reads, and `repo` scope is sufficient for
  private repository reads when the caller already has repository access
- with fine-grained tokens, GitHub documents repository ruleset reads as
  requiring only `Metadata` repository permission (`read`)
- direct organization ruleset reads are not required for `gh-clean`'s
  normal scan path

Important limitation:

- some sensitive fields such as `bypass_actors` may be omitted unless the
  caller has write access to the ruleset
- v1 must not depend on those fields for delete safety

### Vetoes

Vetoes are orthogonal to lifecycle assessment.

#### Hard veto: base of an open PR

A branch must not be deleted if it is currently the base of any open PR.

Reason:

- deleting the branch changes the meaning of a dependent PR
- GitHub may auto-retarget in some flows, but that is still a surprising
  and potentially harmful behavior change

Report label:

- `blocked: base of open PR #123`

#### Hard veto: protection status unknown

If the tool cannot determine whether a branch is protected because of
missing permissions or API failure, deletion must be blocked.

Report label:

- `blocked: protection status unknown`

#### Soft veto: branch tip differs from merge-time head SHA

This applies only to branches whose strongest lifecycle signal is
"merged PR as head."

If the branch's current tip does not match the SHA recorded for the most
recent merged head PR at merge time, the branch should not be considered
automatically deletable. It may still be deletable with explicit user
override.

Report label:

- `review: branch tip differs from merged PR head SHA`

This wording is intentional. The difference may be caused by commits
pushed after merge, or by a force-push that changed the branch without
adding new work.

Soft vetoes affect recommendation but do not by themselves change the
underlying lifecycle classification.

## Classification model

### Role classification

Each branch falls into one of these PR-role buckets:

1. **Has head PRs**: the branch has been used as PR source at least once
2. **Base-only**: the branch has no head PRs but has been used as PR base
3. **No PR involvement**: the branch has no matching PRs as head or base

Fork-sourced PRs must be ignored for head matching unless the PR head
repository matches the repository under evaluation. Matching by branch
name alone is unsafe.

Role classification must be derived from current repository-visible PR
data only. The tool must not attempt to infer deleted historical refs or
missing branches.

### Lifecycle assessment for branches with head PRs

When a branch has one or more PRs as head, determine lifecycle in this
priority order:

1. **Active**: if any head PR is open
2. **Merged**: else if any head PR is merged
3. **Closed-unmerged**: else all head PRs are closed without merge

This priority handles cases where the same branch was reused across
multiple PRs.

### Closed-unmerged interpretation

`closed-unmerged` means exactly this:

- the branch has at least one head PR
- none of those head PRs are open
- none of those head PRs are merged

In other words, every matching head PR for the branch was closed without
merge.

Because of that definition, v1 must not attempt a branch-level
`superseded` sub-classification based only on PRs from the same branch.
That logic is self-contradictory: if the branch had another head PR that
was open or merged, the branch would already classify as `active` or
`merged`.

Instead, the report should treat `closed-unmerged` as a single lifecycle
state and surface additional review signals only:

- count of closed-unmerged head PRs
- most recent PR close time
- whether the tip commit is newer than the most recent PR close time

These signals help distinguish likely abandonment from likely rework in
progress without pretending the tool can prove a branch was "superseded"
from same-branch PR history alone.

### Lifecycle assessment for base-only branches

Base-only branches require special handling because incoming PRs do not
fully describe the branch's own unique commits.

Evaluate them as follows:

1. If the branch is the base of any open PR, apply the hard veto
2. Otherwise, compare the branch tip against the default branch
3. If the branch tip is fully contained in the default branch and all
   incoming PRs are closed or merged, classify it as `integrated`
4. Otherwise, classify it as `base-only-stale-candidate` and treat it as
   requiring manual review using staleness signals

Important nuance:

- "tip contained in default" can mean either "all unique work was
  incorporated" or "the branch never accumulated unique work." Both are
  safe outcomes for deletion, so the distinction does not need a separate
  state.

### Lifecycle assessment for no-PR branches

Branches with no PR involvement are classified as `untracked`.

These are not automatically deletable based on PR data. They require
staleness metadata:

- tip commit date
- tip commit author
- tip commit committer
- branch age if available from ref metadata
- configurable stale threshold

The default stale threshold should be **90 days**. This default is only a
ranking and reporting aid, not an automatic deletion rule by itself.

## Recommendation algorithm

### Required outputs

For each branch, the tool must compute:

- exclusions
- role classification
- lifecycle assessment
- vetoes
- warnings
- final recommendation

### Final recommendation rules

The final recommendation must be derived in this order:

1. If branch is excluded, recommendation is `blocked`
2. Else if protection status is unknown, recommendation is `blocked`
3. Else if branch is base of an open PR, recommendation is `blocked`
4. Else if lifecycle is `active`, recommendation is `keep`
5. Else if lifecycle is `merged` and soft veto is present,
   recommendation is `review`
6. Else if lifecycle is `merged` and no soft veto is present,
   recommendation is `delete-candidate`
7. Else if lifecycle is `integrated`, recommendation is
   `delete-candidate`
8. Else if lifecycle is `closed-unmerged`, recommendation is `review`
9. Else if lifecycle is `base-only-stale-candidate`, recommendation is
   `review`
10. Else if lifecycle is `untracked`, recommendation is `review`

This ordering is normative for v1.

### Why ambiguous branches stay in review

No-PR branches and non-integrated base-only branches may often be stale,
but the design does not have enough evidence to auto-delete them safely.
The report may rank them aggressively, but deletion must still require
human intent.

## Output model

### Human-readable report

The default report output should be a terminal table grouped by
high-signal categories:

1. blocked
2. review recommended
3. likely deletable
4. active / keep

Within groups, sort by:

1. lifecycle category
2. most recent activity descending for active branches
3. staleness descending for cleanup candidates

The default terminal report must be optimized for review, not for
machine parsing.

### Structured report

The tool should also support JSON output. JSON is the canonical format
for automation and for passing report results into the delete command.

CSV may be added later, but JSON should be the first structured output.

### Minimum report fields

Each branch record should include:

- branch name
- current tip SHA
- excluded / protected / unknown-protection flags
- role classification
- lifecycle assessment
- deletion recommendation
- vetoes and warnings
- matching head PR summary
- matching base PR summary
- tip commit date
- tip commit author
- tip commit committer
- stale-threshold comparison

For branches with matching PRs, the report should also include:

- most recent head PR number
- most recent head PR state
- whether the most recent open head PR is draft
- most recent base PR number when applicable

### Recommendation levels

Each branch should end with one recommendation:

- `keep`
- `review`
- `delete-candidate`
- `blocked`

This avoids forcing downstream consumers to reverse-engineer many raw
flags.

### JSON contract

The JSON report must be stable enough for the delete command to consume
across minor releases of v1.

At minimum, each JSON branch record must include:

- `name`
- `tip_sha`
- `excluded_reasons`
- `protection_status`
- `role`
- `lifecycle`
- `vetoes`
- `warnings`
- `recommendation`
- `observed_at`

The top-level JSON object must include:

- repository identifier
- default branch
- stale threshold used
- whether results are complete or partial
- any global warnings such as rate-limit truncation

## Delete workflow

### Inputs

The delete command should accept one of:

- `--branch <name>` repeated
- `--input <report.json>`
- a filter such as `--recommendation delete-candidate`

At least one selector is required.

If `--input <report.json>` is used, the delete command must treat the
report as advisory input, not as authoritative truth. Live re-validation
still decides whether deletion proceeds.

### Re-validation

Deletion must re-check, at minimum, for each selected branch:

- branch still exists
- branch tip SHA still matches the report, unless `--allow-tip-change`
  is set
- branch is not the default branch
- branch is not protected by branch protection rules
- branch is not protected by rulesets
- branch is not base of an open PR
- if using merged-branch logic, branch tip still matches the merge-time
  verification outcome used by the report, unless explicitly overridden

If any of these checks fails, skip the branch and record the reason.

If the branch was selected from a prior report and the branch no longer
appears in the repository, the result should be `skipped: branch no
longer exists`, not a hard command failure.

### Delete semantics

Deletion is best-effort:

- attempt each eligible branch independently
- continue after individual failures
- summarize deleted, skipped, and failed branches at the end

### Overrides

The delete command may support narrow overrides:

- `--force-merged-tip-mismatch` to delete merged branches that fail the
  soft veto
- `--allow-tip-change` to accept branch-tip drift between report and
  delete

It must not support overriding:

- default branch exclusion
- protection / ruleset exclusion
- base-of-open-PR veto
- unknown protection status

If a future version adds more override flags, they must default off and
must never bypass branch protection or default-branch safety rules.

### Audit trail

Every delete run should emit enough information to recreate refs:

- branch name
- deleted tip SHA
- deletion timestamp
- repository
- actor if available from auth context

This can be printed to stdout in structured form and optionally written
to a file.

The audit output must be sufficient to recreate the ref with
`git branch <name> <sha>` after fetching the commit object from the
remote if needed.

## API and query strategy

### Authentication

The tool should integrate with `gh` authentication and use the token
available via `gh auth`.

If required permissions are missing, the tool must fail closed for
deletion-related checks. In particular:

- inability to read PRs means branch classification is incomplete
- inability to read protections or rulesets means deletion must be
  blocked
- inability to delete refs means the report may still run, but delete
  cannot

The report command should still return useful partial information when
safe to do so, but it must clearly mark the run as incomplete.

For rulesets specifically, the authentication requirement is:

- repository read access to the target repository
- for private repositories, token access that covers the repository

Organization-admin permissions are not required for the repository scan
path as long as the repository rulesets endpoint can return inherited
rulesets.

### Repository data needed

The report phase needs:

- repository metadata including default branch
- remote branches and their tip SHAs
- pull requests, including head/base refs, state, draft flag, merge
  status, close and merge timestamps, and repository identity for head
  refs
- branch protection rules
- rulesets that may affect branch deletion
- tip commit metadata per branch

The implementation may obtain branch and commit data from GraphQL, REST,
or a mix of both. The design constrains behavior, not the transport mix.

### Query strategy

Prefer bulk fetch plus local joins over per-branch PR lookups.

The intended query shape is:

1. Fetch repository metadata once
2. Fetch all remote branches with pagination
3. Fetch all relevant PRs with pagination
4. Join branches to PRs locally using repo-qualified head matching and
   direct base-ref matching
5. Evaluate exclusions and lifecycle locally
6. Perform extra per-branch checks only for branches that survive earlier
   filters

The implementation must avoid per-branch PR queries. That pattern is too
expensive and too easy to rate-limit on large repositories.

### Expensive checks

Two checks are potentially expensive and should be deferred:

1. **Base-only ancestry check against default**
2. **Merged-tip divergence check**

These should run only for branches whose earlier classification makes the
result relevant.

### Ancestor / containment check

For base-only branches, use GitHub's compare API with the repository
default branch as base and the candidate branch as head.

Interpretation:

- `behind` or `identical`: branch tip is contained in default
- `ahead` or `diverged`: branch has unique work not contained in default
- error / no common history: unknown, require review

### Performance posture

The tool does not need an incremental cache in v1, but it should avoid
obvious N x M query patterns.

Expected posture:

- paginate all bulk queries to completion
- defer expensive per-branch checks until needed
- optionally bound concurrency for compare requests
- surface rate-limit exhaustion clearly
- return partial report results only when it is safe to label them as
  incomplete

If rate limits prevent completion, the tool must clearly distinguish:

- branches successfully evaluated
- branches not evaluated
- recommendations that are blocked only because evaluation was incomplete

### Merge-time SHA verification

The soft veto depends on finding the head SHA recorded at merge time for
the most recently merged head PR.

This has now been verified against live GitHub behavior.

Verified result:

- GraphQL `headRefOid` on a merged PR behaves as a merge-time snapshot,
  not as a live pointer to the branch's current tip
- REST `pull_request.head.sha` on a merged PR also behaves as a
  merge-time snapshot in the tested case

Observed test case:

- repository: `github/docs`
- branch: `repo-sync`
- merged PRs tested: `#43760`, `#43765`, `#43768`
- current branch tip at verification time matched only the newest merged
  PR's recorded head SHA
- older merged PRs retained older `headRefOid` / `head.sha` values even
  though the branch had since advanced

This is exactly the behavior `gh-clean` needs. Therefore:

1. v1 should use GraphQL `headRefOid` as the primary merge-time SHA field
2. REST `head.sha` may be used as a fallback or spot-check field
3. the timeline merge event is no longer required for this specific
   safety check

Remaining caution:

- this conclusion is based on current GitHub API behavior as verified on
  2026-04-10
- if implementation later encounters contradictory behavior in the wild,
  the design should be updated and merged branches should temporarily
  degrade back to `review`

## Edge cases and limitations

### Stacked PRs

Stacked and cascading PR flows remain a known blind spot. A branch merged
into a non-default integration branch may appear "merged" even if the
integration branch never reached default.

Partial mitigation:

- when a merged head PR targeted a non-default base that still exists,
  check whether that base is contained in default

Residual limitation:

- if the intermediate base branch has been deleted, the tool may not be
  able to prove whether the original work reached default

### Fork PRs

Fork PRs should appear in PR scans but must not be matched to same-named
branches in the target repository unless the repository identity also
matches.

### CI side effects

Deleting a branch may cancel branch-scoped CI or other automation. The
tool does not attempt to model workflow state in v1. This is another
reason the delete flow should be conservative and review-driven.

### Archived repositories

Archived repositories should be treated as report-only by default.
Deletion should refuse to run unless explicitly enabled in a future
version.

### Deleted or renamed branches during a run

The tool must tolerate branches disappearing or changing between report
generation, re-validation, and deletion. These are normal races, not
fatal errors for the overall command.

## Command shape

The exact flag set can evolve, but the intended interface is roughly:

```text
gh clean report [--repo OWNER/REPO] [--format table|json] [--stale-days N]
                [--exclude PATTERN ...] [--filter ...]

gh clean delete [--repo OWNER/REPO]
                (--branch NAME ... | --input REPORT.json | --filter ...)
                [--dry-run]
                [--force-merged-tip-mismatch]
                [--allow-tip-change]
```

The report command should be safe by default. The delete command should
require an explicit selector so that "delete everything deletable" is
always an intentional action.

Flag names may change during implementation, but the workflow constraints
in this section are normative.

## Open questions

These questions should be resolved before implementation is considered
complete:

1. Should report JSON include only derived classifications, or also the
   raw PR/protection evidence used to derive them?
2. Should v1 support markdown output for easy sharing in issues, PRs, or
   chat?

These are usability questions rather than safety blockers. The two
previous blockers have been resolved in the design:

- merge-time SHA: use GraphQL `headRefOid`, with REST `head.sha` as a
  fallback
- ruleset permissions: use the repository rulesets endpoint with
  `includes_parents=true`, not the direct organization ruleset endpoint

## Implementation milestones

1. Build report-only scanning with branch enumeration, PR joins, and
   exclusion handling
2. Add human-readable and JSON output
3. Add deferred expensive checks for base-only branches
4. Implement the merged-tip soft veto using GraphQL `headRefOid`, with
   REST `head.sha` fallback handling
5. Add delete with per-branch re-validation and audit output
