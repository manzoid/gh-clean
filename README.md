# gh-clean

`gh-clean` is a remote GitHub branch cleanup tool. It evaluates branches
using GitHub repository state, produces a report, and can delete
branches after re-validating that they are still safe to remove.

## Requirements

- Python 3.9+
- [GitHub CLI](https://cli.github.com/) installed
- `gh auth login` completed for the target repositories

`gh-clean` currently uses `gh` for GitHub API access and authentication.

## Install

### With `uv`

Install once:

```bash
uv tool install gh-clean
```

Run without installing globally:

```bash
uvx gh-clean report --repo OWNER/REPO
```

### With `pipx`

```bash
pipx install gh-clean
```

## Authenticate

Before using the tool:

```bash
gh auth login
```

If your org requires SAML SSO, authorize the current `gh` token for that
organization as needed.

## Repository config

The target repository must contain a root `.gh-clean.yml` file with a
non-empty `protected_branches` list.

Example:

```yaml
protected_branches:
  - main
  - staging
  - production
```

This list is checked in addition to GitHub branch protection rules and
rulesets.

## Usage

Generate a report:

```bash
gh-clean report --repo OWNER/REPO
gh-clean report --repo OWNER/REPO --format json
```

Add extra protected branches at runtime:

```bash
gh-clean report --repo OWNER/REPO --exclude develop --exclude release/v2
```

Delete from a prior report with re-validation:

```bash
gh-clean report --repo OWNER/REPO --format json > report.json
gh-clean delete --repo OWNER/REPO --input report.json --recommendation delete-candidate --dry-run
gh-clean delete --repo OWNER/REPO --input report.json --recommendation delete-candidate
```

Delete specific branches:

```bash
gh-clean delete --repo OWNER/REPO --branch feature/foo --branch feature/bar --dry-run
```

Override only the merged-tip mismatch soft veto:

```bash
gh-clean delete --repo OWNER/REPO --branch feature/foo --force-merged-tip-mismatch --dry-run
```

## Development

Run directly from the checkout:

```bash
python3 -m gh_clean report --repo gh-clean-sandbox/sandbox
uv run gh-clean report --repo gh-clean-sandbox/sandbox
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```
